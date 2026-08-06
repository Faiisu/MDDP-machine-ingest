# เอกสารการแก้ไข Digital Input และ Channel Rate ของ DAQ USB-4716

เอกสารนี้สรุปปัญหาเดิม สาเหตุ วิธีแก้ไข และวิธีตรวจสอบ Digital Input (DI) รวมถึงการแยก Hardware Clock Rate กับ save rate ราย channel ของ Advantech USB-4716 ในโปรเจกต์ MDDP Ingestion Control Suite

วันที่จัดทำ: 6 สิงหาคม 2026

## สรุปการแก้ไข

USB-4716 มี Digital Input จำนวน 8 ช่อง คือ `DI0` ถึง `DI7` ซึ่งรวมอยู่ใน DI port แบบ 8 บิตเพียง 1 port ไม่ใช่ 5 DI ports ตามที่ config เดิมระบุไว้ เอกสารของ Advantech ระบุ USB-4716 ว่ามี 8 digital input channels และ 8 digital output channels

ใน frontend จึงใช้ `DI_CHANNELS` เป็น setting หลัก ผู้ใช้เลือกเปิด/ปิด `DI0`–`DI7` ได้แยกกันจาก matrix ส่วน `DI_START_PORT`, `DI_PORT_COUNT`, `DI_END_PORT` และ `ENABLE_DI` เป็นค่าภายในสำหรับความเข้ากันได้กับ DAQNavi และ config รุ่นเก่า

ระบบ rate แบ่งเป็น 2 ชั้น: `CLOCK_RATE` คือ Hardware Clock Rate ที่ USB-4716 อ่านจริงร่วมกันทุก AI channel ส่วน `CHANNEL_SAMPLE_RATES` คืออัตราที่ writer จะเลือกบันทึกลงฐานข้อมูลแยกตาม channel เช่น `AI0`, `AI1`, `DI0` และ `DI1` การลด save rate ลดจำนวนข้อมูลปลายทาง แต่ไม่ได้ลดภาระการอ่านของ hardware

การแก้ไขหลักมีดังนี้

- เปลี่ยน frontend จาก `DI Port`/`DI Width` เป็น `DI Channels` ที่เลือกเปิด/ปิดได้รายช่อง
- จำกัด hardware mapping ให้ใช้ port `0` จำนวน `1` port รวม 8 bits เป็นค่าภายใน
- ให้ `DI_CHANNELS` เป็นรายการ boolean 8 ค่า และ derive `ENABLE_DI` จากช่องที่เลือก
- อ่านค่า DI ด้วย `InstantDiCtrl.readAny()` เป็น byte snapshot ต่อการ poll
- บันทึก DI 8 bits เพียงครั้งเดียวต่อ snapshot ไม่ทำซ้ำตามจำนวน AI samples
- ป้องกัน config ที่ระบุ port หรือจำนวน port ไม่ถูกต้อง
- แก้ frontend ไม่ให้การแก้ไข AI ปิด DI โดยอัตโนมัติ
- แก้ตัวคำนวณขนาดข้อมูลให้คิดอัตรา DI ตามรอบการอ่านจริง
- แยก Hardware Clock Rate ออกจาก Save Rate ราย channel ด้วย `CHANNEL_SAMPLE_RATES`
- เพิ่ม time-based decimation ใน parser ให้ AI/DI บันทึกตาม rate ของแต่ละ channel
- แก้การ re-queue เมื่อปลายทางมีปัญหาไม่ให้ข้อมูล DI หาย
- เพิ่ม regression tests สำหรับ DI parser, config validation และ port clipping

อ้างอิง: [Advantech USB-4716 User Manual](https://advdownload.advantech.com/productfile/Downloadfile3/1-26D8IVA/USB-4716_User_Manual_Ed.3-FINAL.pdf)

## ปัญหาเดิมและสาเหตุ

### 1. เข้าใจจำนวน DI port ของอุปกรณ์ผิด

config เดิมใช้ค่าประมาณนี้

```json
{
  "DI_START_PORT": 0,
  "DI_PORT_COUNT": 5,
  "DI_END_PORT": 4
}
```

USB-4716 มีขั้วต่อทางกายภาพหลายชุด แต่ไม่ได้หมายความว่ามี DI port 5 port ใน DAQNavi การส่ง `portCount=5` ไปยัง `readAny()` อาจทำให้ driver อ่านเกินช่วงที่อุปกรณ์รองรับหรืออ่านผิด port

### 2. ค่า DI หนึ่ง snapshot ถูกทำซ้ำทุก AI sample

`InstantDiCtrl.readAny()` เป็นการอ่านค่า DI แบบ instant/static จึงได้ค่า 1 byte ต่อการอ่านหนึ่งครั้ง ไม่ได้คืน sample buffer ที่มีค่า DI ตามเวลาแบบเดียวกับ AI

โค้ดเดิมนำ byte เดียวไปขยายซ้ำใน loop ของ AI ทุก sample ตัวอย่างเช่น

- AI batch มี 500 samples ต่อ channel
- DI มี 1 port = 8 bits
- โค้ดเดิมสร้าง DI rows `500 × 8 = 4,000 rows`
- แต่ข้อมูลจริงจาก DI มีเพียง 8 ค่าใน snapshot เดียว

ผลกระทบคือ

- ได้ค่า DI ซ้ำและ timestamp ไม่สะท้อนการเปลี่ยนแปลงจริง
- จำนวนข้อมูลในฐานข้อมูลเพิ่มขึ้นมากเกินจริง
- ค่า DI ดูเหมือนถูก sample ที่ความถี่เดียวกับ AI ทั้งที่ DI ถูก poll เป็น snapshot

### 3. บันทึก config ที่ไม่ถูกต้องได้

API เดิมรับค่า `DI_START_PORT`, `DI_PORT_COUNT` และ `DI_END_PORT` โดยไม่มีการตรวจสอบหรือคำนวณ `DI_END_PORT` ใหม่ ทำให้ค่าต้นทางและค่าปลายทางไม่สอดคล้องกันได้

### 4. Frontend ปิด DI โดยไม่ได้ตั้งใจ

ตาราง matrix รุ่นเดิมเคยมี DI row toggle แต่ frontend รุ่นปัจจุบันใช้ checkbox `ENABLE_DI` แบบ global แล้ว โค้ดบางส่วนยังค้นหา `.ingest-toggle-di` อยู่ เมื่อไม่พบ row toggle จึงตีความว่าไม่มี DI ที่ active และเปลี่ยน `ENABLE_DI` เป็น `false` ตอนผู้ใช้แก้ไข AI row

นอกจากนี้ฟังก์ชัน sync port range เดิมแก้ค่าใน `activeServerConfig` ซึ่งเป็นค่า baseline สำหรับตรวจ unsaved changes ทำให้บางครั้งแก้ค่า DI แล้วระบบไม่แจ้งว่า config เปลี่ยน

### 5. Data-size estimator คำนวณ DI ที่ความถี่ผิด

โค้ดเดิมคูณ DI bits ด้วย `CLOCK_RATE` เหมือน DI มี sample ทุก clock tick ทั้งที่ DI ถูกอ่านครั้งเดียวต่อ acquisition block จึงแสดงขนาดข้อมูลสูงเกินจริง

### 6. DI หายเมื่อ database หรือ broker ขัดข้อง

เมื่อ writer re-queue batch เดิม โค้ดเดิมสร้าง tuple ใหม่ที่มีเฉพาะข้อมูล AI 3 ส่วน ทำให้ `di_bytes` หายไปในการ retry

### 7. Clock เดียวทำให้ทุก channel ถูกบันทึกถี่เท่ากัน

เดิม `CLOCK_RATE` ถูกใช้ทั้งเป็น hardware acquisition rate และเป็นอัตราที่คาดว่าจะเขียนข้อมูล ทำให้ไม่สามารถอ่าน hardware ที่ rate สูงเพื่อรักษาคุณภาพสัญญาณ แล้วบันทึก channel ที่ไม่ต้องการถี่เท่ากันได้

หลังแก้ไข hardware ยังคงอ่านด้วย `CLOCK_RATE` เดียว แต่ parser ใช้ `CHANNEL_SAMPLE_RATES` กรอง output ตาม timestamp ของแต่ละ channel ค่า rate ที่เว้นว่างหมายถึงใช้ source rate เดิม

## โครงสร้างการทำงานหลังแก้ไข

```mermaid
flowchart LR
    UI[เลือกเปิด/ปิด DI0 ถึง DI7 ใน matrix] --> API[ตรวจสอบและ normalize DI_CHANNELS]
    API --> CFG[DI_CHANNELS + internal port 0 / 1 byte]
    CFG --> READ[InstantDiCtrl.readAny(0, 1)]
    READ --> BYTE[DI byte snapshot]
    BYTE --> BITS[แยกเป็น DI0 ถึง DI7]
    BITS --> MASK[เลือกเฉพาะ channel ที่เปิด]
    MASK --> RATE[กรองตาม CHANNEL_SAMPLE_RATES]
    RATE --> ROWS[สร้าง rows ตาม save rate]
    ROWS --> DB[(PostgreSQL / InfluxDB / MQTT)]
```

เมื่อเปิดใช้ AI ด้วย AI batch จำนวน `N` samples ระบบจะสร้าง

- hardware samples ตาม `CLOCK_RATE`
- AI rows ตาม `CHANNEL_SAMPLE_RATES` ของแต่ละ AI channel
- DI rows ตามจำนวนช่องที่เลือกและ save rate ของแต่ละ DI channel

DI snapshot จะใช้ timestamp ของจุดเริ่มต้นของ acquisition block ไม่ถูกทำซ้ำตลอดทั้ง AI block

## สิ่งที่แก้ในไฟล์หลัก

| ไฟล์ | สิ่งที่แก้ |
| --- | --- |
| [`services/daq_usb4716/app.py`](../services/daq_usb4716/app.py) | ตรวจสอบ config, จำกัด USB-4716 เป็น 1 DI port และคำนวณ `DI_END_PORT` ใหม่ |
| [`services/daq_usb4716/stream_to_db.py`](../services/daq_usb4716/stream_to_db.py) | อ่าน DI ตามจำนวน port ที่อุปกรณ์รายงาน, clip config เก่า และ parse snapshot เป็น 8 rows |
| [`services/daq_usb4716/mockup_stream_to_db.py`](../services/daq_usb4716/mockup_stream_to_db.py) | ให้ mock mode ใช้ DI semantics เดียวกับ real mode |
| [`services/daq_usb4716/rate_control.py`](../services/daq_usb4716/rate_control.py) | ตรวจสอบ rate ราย channel และทำ time-based decimation ก่อนเขียนข้อมูล |
| [`services/daq_usb4716/static/app.js`](../services/daq_usb4716/static/app.js) | ใช้ `DI_CHANNELS`, แสดง toggle DI0–DI7, ตรวจ dirty state, audit diff และคำนวณ data-size ตามช่องที่เลือก |
| [`services/daq_usb4716/templates/index.html`](../services/daq_usb4716/templates/index.html) | เปลี่ยน setting เป็น `Digital Input (DI) Channels` และซ่อน port fields ที่เป็น internal mapping |
| [`services/daq_usb4716/static/style.css`](../services/daq_usb4716/static/style.css) | เพิ่มข้อความช่วยอธิบาย DI configuration |
| [`services/daq_usb4716/config.json`](../services/daq_usb4716/config.json) | ตั้งค่า DI port เป็น `0`, count เป็น `1` และ end port เป็น `0` |
| [`tests/test_daq_usb4716_full.py`](../tests/test_daq_usb4716_full.py) | ทดสอบ DI rows, timestamp, stale port count และ config validation |

## วิธีเปิดใช้งาน DI

### 1. เปิด DAQ console

เปิด browser ไปที่

```text
http://localhost:8081
```

ถ้าใช้งานจากเครื่องอื่น ให้เปลี่ยน `localhost` เป็น IP ของเครื่องที่รัน service

### 2. เลือกช่อง DI ที่ต้องการอ่าน

1. เลือกเมนู **Hardware & Ingestion**
2. ไปที่ตาราง **Channel Ingestion Matrix** และเลือก filter **Digital Input (DI)**
3. เปิด toggle เฉพาะช่องที่ต้องการ เช่น `DI0`, `DI2` และ `DI7`
4. ตั้งค่า `Save Rate (Hz)` ในแต่ละ row ถ้าต้องการ rate ต่ำกว่า source rate; เว้นว่างเพื่อ inherit
5. ตั้งค่า `DB Channel Offset` ตามที่ต้องการ เช่น `100`
6. ตรวจสอบข้อความสรุปจำนวนช่อง เช่น `3/8 DI Channels selected`
7. กด **Save Configuration**
8. กดยืนยัน **Confirm & Write to Disk**
9. หยุดและเริ่ม acquisition ใหม่ หาก process กำลังทำงานอยู่

หมายเหตุ: ไม่ต้องเปิด checkbox global อีกต่อไป ระบบจะตั้ง `ENABLE_DI=true` อัตโนมัติเมื่อมี DI channel อย่างน้อยหนึ่งช่องถูกเลือก และตั้งเป็น `false` เมื่อปิดครบทั้ง 8 ช่อง

## ค่า config ที่เกี่ยวข้อง

| Key | ค่าที่ถูกต้องสำหรับ USB-4716 | ความหมาย |
| --- | ---: | --- |
| `DI_CHANNELS` | array boolean 8 ค่า | ช่อง DI0–DI7 ที่เลือกบันทึก เช่น `[true,false,true,false,false,false,false,true]` |
| `ENABLE_DI` | derive จาก `DI_CHANNELS` | compatibility flag; true เมื่อมีช่องถูกเลือกอย่างน้อยหนึ่งช่อง |
| `DI_START_PORT` | `0` | internal DI port ของ USB-4716 |
| `DI_PORT_COUNT` | `1` | internal: อ่าน 1 byte/port |
| `DI_END_PORT` | `0` | internal: ค่าที่คำนวณจาก start + count - 1 |
| `DI_CHANNEL_OFFSET` | เช่น `100` | channel แรกที่ใช้บันทึก DI |
| `CHANNEL_SAMPLE_RATES` | เช่น `{"AI0":1000,"DI0":1}` | save rate ราย channel; เว้น key หรือค่าไว้เพื่อ inherit source rate |
| `SECTION_LENGTH` | เช่น `500` | จำนวน AI samples ต่อ acquisition block |
| `CLOCK_RATE` | เช่น `2000` | Hardware acquisition clock ร่วมของ AI channels |

ข้อจำกัดของ save rate:

- `AI0`–`AI15` ตั้งได้ไม่เกิน `CLOCK_RATE`
- `DI0`–`DI7` ตั้งได้ไม่เกิน DI snapshot source rate ซึ่งปัจจุบันประมาณ `CLOCK_RATE / SECTION_LENGTH`
- การตั้ง save rate ต่ำลงเป็น software decimation; USB-4716 ยังคงอ่าน hardware ที่ `CLOCK_RATE`

ถ้า `DI_CHANNEL_OFFSET=100` และเลือก `DI0`, `DI2`, `DI7` ช่องที่บันทึกจะเป็น

```text
DI0 -> channel 100
DI2 -> channel 102
DI7 -> channel 107
```

ตัวอย่าง rate:

```json
{
  "CLOCK_RATE": 2000,
  "SECTION_LENGTH": 500,
  "CHANNEL_SAMPLE_RATES": {
    "AI0": 2000,
    "AI1": 100,
    "DI0": 1,
    "DI2": 0.5
  }
}
```

ตัวอย่างนี้ยังอ่าน AI ที่ hardware 2,000 samples/sec แต่บันทึก `AI1` ที่ 100 rows/sec, `DI0` ที่ 1 row/sec และ `DI2` ที่ 0.5 row/sec

## ผลลัพธ์ที่คาดหวัง

ถ้าใช้ `CLOCK_RATE=2000` และ `SECTION_LENGTH=500`

- acquisition block ใช้เวลาประมาณ `500 / 2000 = 0.25 วินาที`
- DI ถูกอ่านประมาณ 4 snapshots ต่อวินาที
- AI ที่ไม่กำหนด override จะถูกบันทึกที่ 2,000 rows/sec ต่อ channel
- AI/DI ที่กำหนด override จะถูกบันทึกตาม rate ราย channel
- ถ้าเปิดครบ 8 ช่อง แต่ละ snapshot สร้าง 8 rows
- ถ้าเปิด 3 ช่อง แต่ละ snapshot สร้าง 3 rows
- DI ไม่ได้สร้าง rows ที่ความถี่ 2,000 ครั้งต่อวินาที

ค่าของแต่ละ row จะเป็น `0.0` หรือ `1.0` และ DI channels ที่เลือกจาก snapshot เดียวกันจะมี timestamp เดียวกัน

## วิธีตรวจสอบจาก log

เมื่อเปิด DI และเริ่ม Real Hardware mode ควรพบข้อความใกล้เคียงนี้ใน console

```text
DAQ DI initialized | device=USB-4716,BID#0 | startPort=0 | portCount=1
DAQ loop started — periodic wall-clock re-anchoring active
```

ถ้า config เก่ายังระบุ port มากเกินไป ระบบจะ clip ให้เหลือ port ที่ hardware รายงาน และเขียน warning ลง log แทนการปล่อยให้ acquisition ล้มทันที

## วิธีตรวจสอบจากฐานข้อมูล

สำหรับ PostgreSQL/TimescaleDB ให้ตรวจ channel 100–107 เช่น

```sql
SELECT time, channel, value
FROM daq_samples
WHERE channel BETWEEN 100 AND 107
ORDER BY time DESC
LIMIT 80;
```

สิ่งที่ควรเห็น

- channel อยู่ในช่วง offset ถึง offset+7 เฉพาะช่องที่เลือก
- value เป็น `0` หรือ `1`
- ช่อง DI ที่เลือกของ snapshot เดียวกันมี timestamp เดียวกัน
- ไม่มี DI rows ซ้ำ 500 ครั้งต่อ AI block

ถ้าใช้ InfluxDB หรือ MQTT ให้ตรวจ measurement/topic ที่ตั้งไว้ โดยมองหา channel เดียวกันใน payload ที่ส่งออก

## Troubleshooting

### ไม่พบข้อความ `DAQ DI initialized`

- ตรวจว่าเลือก DI channel อย่างน้อยหนึ่งช่องใน matrix และบันทึก config แล้ว
- ตรวจว่าเลือก Real Hardware mode
- ตรวจ `DEVICE_DESCRIPTION` เช่น `USB-4716,BID#0`
- ตรวจว่า DAQNavi SDK และ native driver ติดตั้งแล้ว
- ตรวจว่า profile path ถูกต้อง

### พบ `Error reading DI`

- ตรวจสายสัญญาณ DI และ `DGND`
- ตรวจว่าใช้ระดับสัญญาณ TTL ตามสเปกของอุปกรณ์
- ตรวจว่า device ยังอยู่ใน Advantech Navigator
- ตรวจ log ว่า start port เป็น `0` และ count เป็น `1` ซึ่งเป็นค่า internal ของ USB-4716

### เปิด DI แล้วไม่มีข้อมูลในฐานข้อมูล

- กด Save Configuration แล้ว restart acquisition
- ตรวจว่า destination ที่เลือกเชื่อมต่อได้
- ตรวจ channel offset ที่ใช้ query
- ดูค่า `Rows Inserted` และ error ใน terminal

### ค่า DI ไม่เปลี่ยน

DI เป็น instant snapshot ที่อ่านเป็นรอบ ๆ ไม่ใช่ buffered high-speed input แบบ AI ค่าจะคงเดิมจนกว่าจะถึงการ poll ครั้งถัดไป ตรวจระดับแรงดันและกราวด์ของสัญญาณก่อนตรวจ software เพิ่มเติม

### Save Rate สูงกว่าที่ระบบรองรับ

- ลด `AI` save rate ให้ไม่เกิน `CLOCK_RATE`
- ลด `DI` save rate ให้ไม่เกิน `CLOCK_RATE / SECTION_LENGTH`
- ถ้าต้องการ DI ที่เร็วกว่า snapshot source ต้องลด `SECTION_LENGTH` หรือออกแบบ DI polling แยกต่างหาก; การตั้งค่า save rate อย่างเดียวไม่สามารถสร้าง sample ที่ hardware ไม่ได้อ่านได้

## การทดสอบที่เพิ่ม

รัน test ทั้งโปรเจกต์จาก root directory

```bash
python -m pytest -q
node --check services/daq_usb4716/static/app.js
python -m py_compile services/daq_usb4716/*.py
git diff --check
```

ผลการตรวจสอบล่าสุด: `41 passed`

การทดสอบใน workspace นี้ครอบคลุม mock pipeline, parser, API และ SDK wrapper contract ส่วนการทดสอบกับ USB-4716 จริงต้องทำบนเครื่องที่ติดตั้ง DAQNavi native library และเชื่อมต่อ hardware แล้ว
