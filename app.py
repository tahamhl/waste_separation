import sys
from pathlib import Path
from flask import Flask, render_template, request, Response, jsonify, url_for
import os
import uuid
import cv2
import torch
import numpy as np
import pymysql
from datetime import datetime, timedelta
import serial
import time
import threading

# YOLOv5 kök dizinini sisteme tanıt
FILE = Path(__file__).resolve()
ROOT = FILE.parents[0] / 'yolov5' # Proje yapınıza göre bu yolu ayarlayın
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
ROOT = Path(os.path.relpath(ROOT, Path.cwd()))

# YOLOv5 bileşenlerini import et
from models.common import DetectMultiBackend
from utils.dataloaders import IMG_FORMATS, VID_FORMATS, LoadImages, LoadScreenshots, LoadStreams
from utils.general import (LOGGER, Profile, check_file, check_img_size, check_imshow, check_requirements, colorstr,
                           increment_path, non_max_suppression, print_args, scale_boxes, strip_optimizer, xyxy2xywh)
from utils.plots import Annotator, colors
from utils.torch_utils import select_device, smart_inference_mode

app = Flask(__name__)

# Veritabanı bağlantı bilgileri (Lütfen kendi bilgilerinizle güncelleyin)
app.config['MYSQL_HOST'] = '127.0.0.1'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''  # Laragon genellikle boş şifre kullanır
app.config['MYSQL_DB'] = 'bitirme' # Oluşturduğunuz veritabanının adı

# Tespitler için bekleme süresi (saniye)
DETECTION_COOLDOWN_SECONDS = 10 
# Her nesne türü için son tespit zamanını saklayan sözlük
LAST_DETECTION_TIMES = {}

# Tespit edilen nesne sınıfına göre servo açısını belirleyen harita
# NOT: Buradaki 'plastik', 'metal' gibi isimler modelinizin 'names' listesindeki
# isimlerle BİREBİR AYNI olmalıdır. Gerekirse bu isimleri güncelleyin.
NESNE_ACI_MAP = {
    'Plastic': 0,        # Plastik
    'Metal': 90,         # Metal
    'Glass': 45,         # Cam
    'Paper': 135,        # Kağıt
    'PlasticBag': 180,   # Poşet (veya başka bir açı)
}

# --- Sade ve garantili sayaç/kilit mantığı için değişkenler ---
SON_CLASS = None
SON_CLASS_START = None
KILIT = False
KILIT_SURESI = 5  # servo işlemi süresi (sn)

# --- Ayırma servosunun son pozisyonunu tutan değişken ---
SON_AYIRMA_ACISI = None  # S1'in son pozisyonu

def get_db_connection():
    """Veritabanı bağlantısı oluşturur."""
    try:
        conn = pymysql.connect(host=app.config['MYSQL_HOST'],
                               user=app.config['MYSQL_USER'],
                               password=app.config['MYSQL_PASSWORD'],
                               db=app.config['MYSQL_DB'],
                               cursorclass=pymysql.cursors.DictCursor,
                               connect_timeout=10) # Zaman aşımı ekleyin
        return conn
    except pymysql.MySQLError as e:
        LOGGER.info(f"Veritabanı bağlantı hatası: {e}")
        return None

# Yüklenen dosyaların ve sonuçların kaydedileceği yolları belirle
UPLOAD_FOLDER = 'static/uploads'
DETECTION_FOLDER = 'static/detections'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DETECTION_FOLDER'] = DETECTION_FOLDER

# Klasörlerin var olduğundan emin ol
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DETECTION_FOLDER, exist_ok=True)

# Modeli ve diğer bileşenleri yükle (uygulama başlangıcında bir kez)
DEVICE = select_device('') # Cihazı seç (CPU veya GPU)
MODEL_PATH = 'yolov5/runs/train/exp4/weights/best.pt'
model = DetectMultiBackend(MODEL_PATH, device=DEVICE, dnn=False, data=ROOT / 'data/coco128.yaml', fp16=False)
STRIDE, NAMES, PT = model.stride, model.names, model.pt
IMG_SIZE = check_img_size((640, 640), s=STRIDE)

def save_detections_to_db(detections):
    """Tespit edilen nesneleri bekleme süresini dikkate alarak veritabanına kaydeder."""
    conn = get_db_connection()
    if not conn:
        return

    now = datetime.now()
    new_detections_to_save = []

    for detection_class in detections:
        last_time = LAST_DETECTION_TIMES.get(detection_class)
        if not last_time or (now - last_time) > timedelta(seconds=DETECTION_COOLDOWN_SECONDS):
            new_detections_to_save.append(detection_class)
            LAST_DETECTION_TIMES[detection_class] = now # Zamanı güncelle
    
    if not new_detections_to_save:
        if conn:
            conn.close()
        return

    try:
        with conn.cursor() as cursor:
            # Her yeni nesne için ayrı kayıt oluştur
            for detection_class in new_detections_to_save:
                # Her nesne için kendi güncellenmiş zaman damgasını kullan
                sql = "INSERT INTO `tespitler` (`nesne_turu`, `tespit_zamani`) VALUES (%s, %s)"
                cursor.execute(sql, (detection_class, LAST_DETECTION_TIMES[detection_class]))
        conn.commit()
    except pymysql.MySQLError as e:
        LOGGER.info(f"Veritabanına yazma hatası: {e}")
    finally:
        if conn:
            conn.close()

# --- Güncellenmiş servo_islemleri fonksiyonu ---
def servo_islemleri(ayirma_aci, bosaltma_aci1=0, bosaltma_aci2=70):
    """
    Ayırma servosu (S1) sadece yeni bir açıya gitmesi gerekiyorsa hareket eder,
    aynı açıda ise tekrar hareket etmez. Boşaltma servosu (S2) ise her zaman 0'a gidip tekrar 70'e döner.
    Bu sayede ayırma servosu gereksiz yere tekrar tekrar hareket etmez, motorlar korunur ve sistem daha verimli çalışır.
    """
    global SON_AYIRMA_ACISI
    try:
        arduino = serial.Serial('COM3', 9600, timeout=2)
        time.sleep(5)  # Arduino'nun tamamen hazır olması için bekleme süresi artırıldı
        # Ayırma servosu sadece farklı açıya gitmesi gerekiyorsa hareket etsin
        if SON_AYIRMA_ACISI != ayirma_aci:
            try:
                arduino.write(f'S1,{ayirma_aci}\n'.encode())
                print(f"[BİLGİ] S1,{ayirma_aci} komutu gönderildi.")
                SON_AYIRMA_ACISI = ayirma_aci
                time.sleep(2)
            except Exception as e:
                print(f"[HATA] S1 komutu gönderilemedi: {e}")
        else:
            print(f"[BİLGİ] S1 zaten {ayirma_aci} derecede, tekrar hareket etmeyecek.")
        # Boşaltma servosu
        try:
            arduino.write(f'S2,{bosaltma_aci1}\n'.encode())
            print(f"[BİLGİ] S2,{bosaltma_aci1} komutu gönderildi.")
            time.sleep(3)
            arduino.write(f'S2,{bosaltma_aci2}\n'.encode())
            print(f"[BİLGİ] S2,{bosaltma_aci2} komutu gönderildi.")
            time.sleep(2)
        except Exception as e:
            print(f"[HATA] S2 komutları gönderilemedi: {e}")
        arduino.close()
        print('[BİLGİ] Tüm servo işlemleri başarıyla gönderildi.')
    except Exception as e:
        print(f'[HATA] Servo işlemleri sırasında hata: {e}')

def detect_objects_on_image(image_path):
    global SON_CLASS, SON_CLASS_START, KILIT
    im = cv2.imread(image_path)
    im0 = im.copy()
    
    # Görüntüyü modele uygun formata getir
    img = letterbox(im, IMG_SIZE, stride=STRIDE, auto=PT)[0]
    img = img.transpose((2, 0, 1))[::-1]  # HWC to CHW, BGR to RGB
    img = np.ascontiguousarray(img)

    img = torch.from_numpy(img).to(DEVICE)
    img = img.half() if model.fp16 else img.float()
    img /= 255.0
    if len(img.shape) == 3:
        img = img[None]

    # Model ile çıkarım yap
    pred = model(img, augment=False, visualize=False)
    
    # NMS (Non-Maximum Suppression) uygula
    pred = non_max_suppression(pred, 0.25, 0.45, classes=None, max_det=1000)

    detections_info = []
    # Tespitleri işle
    for i, det in enumerate(pred):
        annotator = Annotator(im0, line_width=2, example=str(NAMES))
        if len(det):
            det[:, :4] = scale_boxes(img.shape[2:], det[:, :4], im0.shape).round()
            for *xyxy, conf, cls in reversed(det):
                c = int(cls)
                label = f'{NAMES[c]} {conf:.2f}'
                annotator.box_label(xyxy, label, color=colors(c, True))
                detections_info.append(NAMES[c])

    if detections_info:
        save_detections_to_db(detections_info)
        ilk_tespit = detections_info[0]
        now = datetime.now()
        print(f"[SIMPLE] ilk_tespit: {ilk_tespit}, SON_CLASS: {SON_CLASS}, SON_CLASS_START: {SON_CLASS_START}, KILIT: {KILIT}")
        LOGGER.info(f"[SIMPLE] ilk_tespit: {ilk_tespit}, SON_CLASS: {SON_CLASS}, SON_CLASS_START: {SON_CLASS_START}, KILIT: {KILIT}")
        if KILIT:
            print("[SIMPLE] KILIT aktif, yeni işlem başlatılmayacak.")
            LOGGER.info("[SIMPLE] KILIT aktif, yeni işlem başlatılmayacak.")
            return
        if SON_CLASS == ilk_tespit:
            if SON_CLASS_START and (now - SON_CLASS_START).total_seconds() >= 3:
                print(f"[SIMPLE] 3 saniye boyunca '{ilk_tespit}' tespit edildi. Servo işlemi başlatılıyor.")
                LOGGER.info(f"[SIMPLE] 3 saniye boyunca '{ilk_tespit}' tespit edildi. Servo işlemi başlatılıyor.")
                KILIT = True
                hedef_aci = NESNE_ACI_MAP.get(ilk_tespit)
                if hedef_aci is not None:
                    servo_islemleri(hedef_aci)
                else:
                    print(f"[SIMPLE] NESNE_ACI_MAP'te '{ilk_tespit}' için eşleşme yok.")
                    LOGGER.warning(f"[SIMPLE] NESNE_ACI_MAP'te '{ilk_tespit}' için eşleşme yok.")
                KILIT = False
                SON_CLASS = None
                SON_CLASS_START = None
        else:
            print(f"[SIMPLE] Yeni class tespit edildi: {ilk_tespit}. Sayaç başlatılıyor.")
            LOGGER.info(f"[SIMPLE] Yeni class tespit edildi: {ilk_tespit}. Sayaç başlatılıyor.")
            SON_CLASS = ilk_tespit
            SON_CLASS_START = now
    result_img = annotator.result()
    
    # Sonuçları kaydet
    filename = str(uuid.uuid4()) + ".jpg"
    save_path = os.path.join(app.config['DETECTION_FOLDER'], filename)
    cv2.imwrite(save_path, result_img)

    return save_path, ", ".join(detections_info)

def letterbox(im, new_shape=(640, 640), color=(114, 114, 114), auto=True, scaleFill=False, scaleup=True, stride=32):
    shape = im.shape[:2]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    if not scaleup:
        r = min(r, 1.0)
    ratio = r, r
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    if auto:
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)
    elif scaleFill:
        dw, dh = 0.0, 0.0
        new_unpad = (new_shape[1], new_shape[0])
        ratio = new_shape[1] / shape[1], new_shape[0] / shape[0]
    dw /= 2
    dh /= 2
    if shape[::-1] != new_unpad:
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return im, ratio, (dw, dh)

@app.route('/')
def index():
    """Ana sayfayı render eder."""
    return render_template('index.html')

@app.route('/history')
def history():
    """Tespit geçmişini gösterir."""
    conn = get_db_connection()
    detections = []
    if conn:
        try:
            with conn.cursor() as cursor:
                # Silme işlemi için ID'yi de al
                sql = "SELECT `id`, `nesne_turu`, `tespit_zamani` FROM `tespitler` ORDER BY `tespit_zamani` DESC"
                cursor.execute(sql)
                detections = cursor.fetchall()
        except pymysql.MySQLError as e:
            LOGGER.info(f"Veritabanından okuma hatası: {e}")
        finally:
            conn.close()
    return render_template('history.html', detections=detections)

@app.route('/delete/<int:detection_id>', methods=['POST'])
def delete_detection(detection_id):
    """Belirli bir tespiti veritabanından siler."""
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                sql = "DELETE FROM `tespitler` WHERE `id` = %s"
                cursor.execute(sql, (detection_id,))
            conn.commit()
            return jsonify({'success': True, 'message': 'Kayıt başarıyla silindi.'})
        except pymysql.MySQLError as e:
            LOGGER.info(f"Veritabanından silme hatası: {e}")
            return jsonify({'success': False, 'message': 'Silme işlemi sırasında bir hata oluştu.'})
        finally:
            conn.close()
    return jsonify({'success': False, 'message': 'Veritabanı bağlantısı kurulamadı.'})

@app.route('/delete_all', methods=['POST'])
def delete_all_detections():
    """Tüm tespit kayıtlarını veritabanından siler."""
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                sql = "TRUNCATE TABLE `tespitler`"
                cursor.execute(sql)
            conn.commit()
            return jsonify({'success': True, 'message': 'Tüm kayıtlar başarıyla silindi.'})
        except pymysql.MySQLError as e:
            LOGGER.info(f"Veritabanından toplu silme hatası: {e}")
            return jsonify({'success': False, 'message': 'Toplu silme işlemi sırasında bir hata oluştu.'})
        finally:
            conn.close()
    return jsonify({'success': False, 'message': 'Veritabanı bağlantısı kurulamadı.'})

@app.route('/predict_image', methods=['POST'])
def predict_image():
    """Yüklenen resim üzerinde nesne tespiti yapar ve sonucu döndürür."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Dosya bulunamadı'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Dosya seçilmedi'})
    if file:
        filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        result_path, detections = detect_objects_on_image(filepath)
        
        return jsonify({
            'success': True, 
            'image_url': '/' + result_path.replace('\\', '/'),
            'detections': f'Tespit edilen nesneler: {detections}' if detections else 'Herhangi bir nesne tespit edilemedi.'
        })

def gen_frames(cam_index=0):
    global SON_CLASS, SON_CLASS_START, KILIT
    cap = cv2.VideoCapture(cam_index)
    while True:
        success, frame = cap.read()
        if not success:
            break
        else:
            # Görüntüyü modele uygun formata getir
            img = letterbox(frame, IMG_SIZE, stride=STRIDE, auto=PT)[0]
            img = img.transpose((2, 0, 1))[::-1]
            img = np.ascontiguousarray(img)
            
            img = torch.from_numpy(img).to(DEVICE)
            img = img.half() if model.fp16 else img.float()
            img /= 255.0
            if len(img.shape) == 3:
                img = img[None]

            # Çıkarım
            pred = model(img, augment=False, visualize=False)
            pred = non_max_suppression(pred, 0.25, 0.45, classes=None, max_det=1000)
            
            detections_this_frame = []
            # Tespitleri çiz
            for i, det in enumerate(pred):
                annotator = Annotator(frame, line_width=2, example=str(NAMES))
                if len(det):
                    det[:, :4] = scale_boxes(img.shape[2:], det[:, :4], frame.shape).round()
                    for *xyxy, conf, cls in reversed(det):
                        c = int(cls)
                        label = f'{NAMES[c]} {conf:.2f}'
                        annotator.box_label(xyxy, label, color=colors(c, True))
                        detections_this_frame.append(NAMES[c])
            
            if detections_this_frame:
                save_detections_to_db(detections_this_frame)
                ilk_tespit = detections_this_frame[0]
                now = datetime.now()
                print(f"[SIMPLE] ilk_tespit: {ilk_tespit}, SON_CLASS: {SON_CLASS}, SON_CLASS_START: {SON_CLASS_START}, KILIT: {KILIT}")
                LOGGER.info(f"[SIMPLE] ilk_tespit: {ilk_tespit}, SON_CLASS: {SON_CLASS}, SON_CLASS_START: {SON_CLASS_START}, KILIT: {KILIT}")
                if KILIT:
                    print("[SIMPLE] KILIT aktif, yeni işlem başlatılmayacak.")
                    LOGGER.info("[SIMPLE] KILIT aktif, yeni işlem başlatılmayacak.")
                    continue
                if SON_CLASS == ilk_tespit:
                    if SON_CLASS_START and (now - SON_CLASS_START).total_seconds() >= 3:
                        print(f"[SIMPLE] 3 saniye boyunca '{ilk_tespit}' tespit edildi. Servo işlemi başlatılıyor.")
                        LOGGER.info(f"[SIMPLE] 3 saniye boyunca '{ilk_tespit}' tespit edildi. Servo işlemi başlatılıyor.")
                        KILIT = True
                        hedef_aci = NESNE_ACI_MAP.get(ilk_tespit)
                        if hedef_aci is not None:
                            servo_islemleri(hedef_aci)
                        else:
                            print(f"[SIMPLE] NESNE_ACI_MAP'te '{ilk_tespit}' için eşleşme yok.")
                            LOGGER.warning(f"[SIMPLE] NESNE_ACI_MAP'te '{ilk_tespit}' için eşleşme yok.")
                        KILIT = False
                        SON_CLASS = None
                        SON_CLASS_START = None
                else:
                    print(f"[SIMPLE] Yeni class tespit edildi: {ilk_tespit}. Sayaç başlatılıyor.")
                    LOGGER.info(f"[SIMPLE] Yeni class tespit edildi: {ilk_tespit}. Sayaç başlatılıyor.")
                    SON_CLASS = ilk_tespit
                    SON_CLASS_START = now
            result_frame = annotator.result()
            ret, buffer = cv2.imencode('.jpg', result_frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    """Video akışını döndüren route."""
    cam_index = int(request.args.get('cam', 0))  # Varsayılan 0
    return Response(gen_frames(cam_index), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/export_history')
def export_history():
    """Tespit geçmişini JSON olarak dışa aktarır."""
    conn = get_db_connection()
    detections = []
    if conn:
        try:
            with conn.cursor() as cursor:
                sql = "SELECT `id`, `nesne_turu`, `tespit_zamani` FROM `tespitler` ORDER BY `tespit_zamani` DESC"
                cursor.execute(sql)
                rows = cursor.fetchall()
                for row in rows:
                    detections.append({
                        'id': row['id'],
                        'nesne_turu': row['nesne_turu'],
                        'tespit_zamani': row['tespit_zamani'].strftime('%Y-%m-%d %H:%M:%S')
                    })
        except Exception as e:
            return jsonify({'success': False, 'message': 'Veritabanı okuma hatası', 'error': str(e)})
        finally:
            conn.close()
    return jsonify({'success': True, 'detections': detections})

@app.route('/farkindalik')
def farkindalik():
    return render_template('farkindalik.html')

@app.route('/servo_control', methods=['POST'])
def servo_control():
    """Servo motoru verilen açıya döndürür."""
    data = request.get_json()
    if not data or 'aci' not in data:
        return jsonify({'success': False, 'message': 'Açı bilgisi gönderilmedi.'}), 400
    try:
        aci = int(data['aci'])
        if not (0 <= aci <= 180):
            return jsonify({'success': False, 'message': 'Açı 0-180 arasında olmalı.'}), 400
    except ValueError:
        return jsonify({'success': False, 'message': 'Açı sayısal olmalı.'}), 400
    sonuc = servo_gonder(aci)
    return jsonify({'success': True, 'message': sonuc})

def servo_gonder(aci):
    try:
        arduino = serial.Serial('COM3', 9600, timeout=1)
        time.sleep(2)  # Arduino'nun hazır olması için bekle
        arduino.write(f"{aci}\n".encode())
        time.sleep(0.5)
        cevap = ""
        while arduino.in_waiting:
            cevap += arduino.readline().decode(errors='ignore').strip() + "\n"
        arduino.close()
        return cevap if cevap else "Komut gönderildi."
    except Exception as e:
        return f"Bağlantı hatası: {e}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 