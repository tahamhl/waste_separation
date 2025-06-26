# ♻️ waste_separation

**Akıllı Atık Sınıflandırma ve Otomatik Boşaltma Sistemi**  
Görüntü İşleme + YOLOv5 + Arduino + Servo Motor + Flask Web Arayüzü  
> Geliştirici: [tahamhl](https://github.com/tahamhl)

---

## 🚀 Proje Hakkında

Bu proje, atıkların (plastik, metal, cam, kağıt, poşet vb.) **görüntü işleme ve yapay zeka** ile otomatik olarak sınıflandırılması ve uygun hazneye yönlendirilmesini sağlar.  
Ayrıca, **Arduino tabanlı donanım** ile fiziksel ayrıştırma ve otomatik boşaltma işlemleri gerçekleştirilir.

- **Gerçek zamanlı nesne tespiti:** YOLOv5 ile.
- **Web arayüzü:** Flask ile dosya yükleme ve canlı kamera desteği.
- **Donanım entegrasyonu:** Arduino Uno ve 2 adet servo motor.
- **Akıllı kontrol algoritması:** Motor ömrünü korur, gereksiz hareketi engeller.

---

## 📸 Demo

![chrome_9Zn4v8Fvis](https://github.com/user-attachments/assets/0019624a-8ee6-4a6e-bb1d-061b87249edd)



---

## 🛠️ Sistem Mimarisi

```
Kamera
   │
   ▼
Bilgisayar (Python + Flask + YOLOv5)
   │
   ▼
Arduino Uno (Serial)
   │
   ▼
Servo Motorlar (Ayırma & Boşaltma)
   │
   ▼
Fiziksel Atık Haznesi
```

---

## 🔥 Özellikler

- **Gerçek zamanlı atık tespiti ve sınıflandırma**
- **3 saniye boyunca aynı nesne tespit edilirse otomatik ayrıştırma**
- **Ayırma servosu sadece yeni açıya gitmesi gerekiyorsa hareket eder**
- **Boşaltma servosu her zaman 70 derecede bekler, boşaltma sırasında 0'a gider ve tekrar 70'e döner**
- **Kullanıcı dostu web arayüzü**
- **Detaylı loglama ve hata yönetimi**
- **Donanım ve yazılım tam entegre**

---

## 📦 Kurulum

### 1. Gerekli Donanım

- Arduino Uno
- 2x Servo Motor (SG90 veya benzeri)
- USB Kamera veya Webcam
- Atık haznesi (prototip için kutu veya 3D baskı)
- Bağlantı kabloları

### 2. Arduino Kodu

Arduino IDE ile aşağıdaki kodu yükleyin:

```cpp
#include <Servo.h>
Servo ayirmaServo;  // Pin 7
Servo bosaltmaServo; // Pin 11

void setup() {
  Serial.begin(9600);
  ayirmaServo.attach(7);
  bosaltmaServo.attach(11);
  ayirmaServo.write(90);
  bosaltmaServo.write(70);
}

void loop() {
  if (Serial.available() > 0) {
    String komut = Serial.readStringUntil('\n');
    komut.trim();
    if (komut.startsWith("S")) {
      int virgulIndex = komut.indexOf(',');
      if (virgulIndex > 0) {
        int servoNo = komut.substring(1, virgulIndex).toInt();
        int aci = komut.substring(virgulIndex + 1).toInt();
        if (servoNo == 1) ayirmaServo.write(aci);
        else if (servoNo == 2) bosaltmaServo.write(aci);
      }
    }
  }
}
```

### 3. Python Ortamı

```bash
git clone https://github.com/tahamhl/waste_separation.git
cd waste_separation
python -m venv venv
venv\Scripts\activate  # (Windows) veya source venv/bin/activate (Linux/Mac)
pip install -r yolov5/requirements.txt
pip install flask opencv-python pyserial
```

### 4. YOLOv5 Modeli

- Kendi veri setinizle eğitilmiş YOLOv5 modelinizi `yolov5/runs/train/exp/weights/best.pt` olarak yerleştirin.
- Sınıf isimleri: `['Glass', 'Metal', 'Paper', 'Plastic', 'PlasticBag']`

### 5. Uygulamayı Başlat

```bash
python app.py
```
- Web arayüzüne erişim:  
  `http://localhost:5000/` veya ağ üzerinden `http://<bilgisayar_ip_adresi>:5000/`

### 🗄️ MySQL Veritabanı Kurulumu ve Bağlantı

Bu proje, tespit edilen nesneleri kaydetmek için bir MySQL veritabanı kullanır. Aşağıdaki adımları izleyerek veritabanı bağlantısını kurabilirsiniz:

### 1. MySQL Veritabanı Oluşturma

Öncelikle bir MySQL veritabanı oluşturun (örneğin: `bitirme`).

```sql
CREATE DATABASE bitirme;
```

### 2. Tespitler Tablosunu Oluşturma

Aşağıdaki SQL komutunu kullanarak tespitlerin kaydedileceği tabloyu oluşturun:

```sql
CREATE TABLE tespitler (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nesne_turu VARCHAR(50),
    tespit_zamani DATETIME
);
```

### 3. Bağlantı Ayarları

`app.py` dosyasında aşağıdaki ayarları kendi MySQL bilgilerinizle güncelleyin:

```python
app.config['MYSQL_HOST'] = '127.0.0.1'      # MySQL sunucu adresi
app.config['MYSQL_USER'] = 'root'           # MySQL kullanıcı adı
app.config['MYSQL_PASSWORD'] = ''           # MySQL şifresi (varsayılan: boş)
app.config['MYSQL_DB'] = 'bitirme'          # Oluşturduğunuz veritabanı adı
```

> **Not:** Laragon gibi yerel sunucularda şifre genellikle boştur. Kendi şifrenizi kullanıyorsanız bu alanı güncellemeyi unutmayın.

---

## ⚙️ Kullanım

- Web arayüzünden resim yükleyin veya canlı kamera akışını başlatın.
- Sistem, atığı otomatik olarak sınıflandırır ve uygun hazneye yönlendirir.
- Boşaltma işlemi otomatik olarak gerçekleşir.
- Tüm işlemler ve hatalar loglanır.

---

## 🧠 Proje Detayları

### Akıllı Kontrol Algoritması
- 3 saniye boyunca aynı nesne tespit edilirse servo işlemi başlatılır.
- Ayırma servosu sadece yeni bir açıya gitmesi gerekiyorsa hareket eder.
- Boşaltma servosu her zaman 70 derecede bekler, boşaltma sırasında 0'a gider ve tekrar 70'e döner.
- Tüm işlemler sırasında sistem kilitlenir, yeni komut alınmaz.

### Sınıf ve Açı Eşleşmesi
```python
NESNE_ACI_MAP = {
    'Plastic': 0,
    'Metal': 45,
    'Glass': 90,
    'Paper': 135,
    'PlasticBag': 180
}
```

---

## 🧪 Testler

- Farklı atık türleriyle (plastik, metal, cam, kağıt, poşet) test edildi.
- Her sınıf için doğru servo açısı ve boşaltma işlemi başarıyla gerçekleşti.
- Gerçek zamanlı performans ve hata yönetimi testleri yapıldı.

---

## 📝 Katkıda Bulunma

1. Fork'la ve kendi branch'inde çalış.
2. Pull request gönder.
3. Hataları veya önerileri [issue](https://github.com/tahamhl/waste_separation/issues) olarak bildir.

---

## 📚 Kaynakça

- [YOLOv5](https://github.com/ultralytics/yolov5)
- [Arduino](https://www.arduino.cc/)
- [Flask](https://flask.palletsprojects.com/)
- [OpenCV](https://opencv.org/)
- [PySerial](https://pyserial.readthedocs.io/)

---

### 🏷️ Model Ağırlıkları (`best.pt`) Nasıl Eklenir?

- YOLOv5 ile eğitilmiş model ağırlığı dosyası (`best.pt`) repoya eklenmemiştir. Aşağıdaki bağlantıdan indirebilirsiniz:

  [best.pt dosyasını indir (Google Drive)](https://drive.google.com/file/d/1jMTDqLdhhCDqrbttOtkp7aoP_5X5YrbG/view?usp=sharing)

- İndirdikten sonra, dosyayı şu dizine yerleştirin:
  ```
  yolov5/runs/train/exp4/weights/best.pt
  ```
- Eğer `weights` veya `exp4` klasörleri yoksa, kendiniz oluşturabilirsiniz.
- Uygulama başlatıldığında model otomatik olarak bu dosyayı kullanacaktır.

> **Not:** Model dosyası büyük boyutlu olduğu için doğrudan GitHub repoya eklenmemiştir.

---

## 📣 Lisans

MIT License

Copyright (c) 2025 Mehmet Taha Mehel

İzin, bu yazılımın ve ilgili dokümantasyon dosyalarının ("Yazılım") bir kopyasını, Yazılımın kısıtlama olmaksızın kullanılması, kopyalanması, değiştirilmesi, birleştirilmesi, yayımlanması, dağıtılması, alt lisansı verilmesi ve/veya satılması için ücretsiz olarak verilmiştir ve Yazılımın sağlandığı kişilere aşağıdaki koşullara tabi olarak bunu yapma izni verilir:

Yukarıdaki telif hakkı bildirimi ve bu izin bildirimi, Yazılımın tüm kopyalarına veya önemli bölümlerine eklenmelidir.

YAZILIM "OLDUĞU GİBİ" SAĞLANMAKTADIR, AÇIK VEYA ZIMNİ HİÇBİR GARANTİ VERİLMEMEKTEDİR; bunlara PAZARLANABİLİRLİK, BELİRLİ BİR AMACA UYGUNLUK ve İHLAL ETMEME garantileri dahildir ancak bunlarla sınırlı değildir. Hiçbir durumda yazarlar veya telif hakkı sahipleri, Yazılımdan veya Yazılımın kullanılmasından ya da başka şekillerde Yazılımla ilgili ortaya çıkan hiçbir iddia, zarar veya diğer yükümlülüklerden sorumlu tutulamazlar.

---

## ✨ Geliştirici

- [tahamhl](https://github.com/tahamhl)

---

> **Not:**  
> Bu proje, bitirme tezi kapsamında geliştirilmiştir.  
> Her türlü öneri, katkı ve geri bildirim için iletişime geçebilirsiniz! 
