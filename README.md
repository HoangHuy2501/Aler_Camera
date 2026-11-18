# Cảnh báo camera

`client/` là ứng dụng Next.js. `server/` là API FastAPI, worker nhận sự kiện và schema PostgreSQL.

| Vai trò | Quyền |
| --- | --- |
| Quản trị viên | Thêm, sửa, tắt hoặc xóa tối đa 20 camera. Tạo, khóa, mở lại tài khoản người dùng, cấp quyền xem từng camera và đặt lại mật khẩu. |
| Người dùng | Xem ảnh và cảnh báo của camera được cấp quyền. Chọn giờ và loại sự kiện muốn nhận. |

Mọi tài khoản đăng nhập bằng email và mật khẩu. Đường dẫn đặt lại mật khẩu gửi qua SMTP, có hiệu lực 30 phút và dùng một lần. Quản trị viên đầu tiên được tạo bằng CLI.

## 1. Chuẩn bị PostgreSQL và quản trị viên

Cần Node.js 20.9+, Python 3.11+, PostgreSQL 14+ và máy chạy worker có đường mạng đến camera hoặc Frigate. Cài FFmpeg nếu cần chụp ảnh từ RTSP.

Chạy từ thư mục gốc repo trên Linux/macOS.

```bash
cd server
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Trên Windows PowerShell, kích hoạt bằng `.\.venv\Scripts\Activate.ps1` và dùng `Copy-Item .env.example .env`.

Điền `DATABASE_URL` và dán khóa vừa tạo vào `CAMERA_SECRET_KEY` trong `server/.env`. Giữ khóa để worker đọc được thông tin camera đã lưu. Tài khoản PostgreSQL chạy schema cần quyền tạo bảng và chỉ mục. Chọn database riêng cho ứng dụng. Schema có thể chạy lại để khởi tạo cùng phiên bản.

```bash
python manage.py schema
python manage.py create-admin --email admin@example.com --name "Quản trị viên"
```

Schema nằm ở `server/schema.sql`. Có thể chạy tập tin này bằng `psql` hoặc trình SQL thay cho lệnh `manage.py schema`.

## 2. Chạy ba tiến trình

Mở ba terminal tại thư mục gốc repo. Hai terminal trong `server/` dùng môi trường Python đã kích hoạt ở bước 1.

| Tiến trình | Thư mục | Lệnh |
| --- | --- | --- |
| API | `server/` | `python -m uvicorn main:app --host 127.0.0.1 --port 8000` |
| Worker | `server/` | `python worker.py` |
| Web | `client/` | `npm ci` rồi `npm run dev` |

Mở [web cục bộ](http://127.0.0.1:3000). Đăng nhập quản trị viên, thêm camera, rồi tạo người dùng và cấp quyền trong mục **Người dùng**. Khung mặc định 22:00–06:00 tính theo giờ Việt Nam. Cảnh báo bắt đầu lúc 22:00 và dừng lúc 06:00. Hai mốc bằng nhau áp dụng cả ngày. Lịch áp dụng cho từng tài khoản và cho các sự kiện mới phát sinh. Web tải cảnh báo mới mỗi 5 giây khi mở mục **Cảnh báo**.

## 3. Thử IMOU qua ONVIF

1. Đặt máy chạy worker cùng mạng với IMOU Ranger 2-L-3B32. Bật tính năng phát hiện người và chuyển động trong phần cài đặt camera. Xác định IP, cổng ONVIF và thông tin đăng nhập cục bộ từ thiết bị/mạng của bạn.
2. Thêm camera với nguồn **ONVIF trực tiếp**. Nhập địa chỉ, cổng, tên đăng nhập và mật khẩu. Nếu đã xác minh luồng RTSP bằng VLC hoặc FFmpeg, điền luồng đó để lấy ảnh dự phòng.
3. Để kiểm tra camera ID `1`, từ `server/` chạy `python worker.py --diagnose 1`. Đi ngang camera và đọc dòng chủ đề ONVIF, loại sự kiện nhận dạng và kết quả lấy JPEG. ID nằm trong danh sách camera của quản trị viên. Dùng Ctrl+C để kết thúc.
4. Bật worker chính và tạm đặt lịch cả ngày để thử cảnh báo. Kiểm tra ảnh, giờ và loại sự kiện trong web. Sau đó đặt lại lịch 22:00–06:00.

ONVIF dùng PullPoint để đọc sự kiện, thử lấy JPEG qua GetSnapshotUri và dùng FFmpeg nếu có RTSP dự phòng. Trạng thái **Đã kết nối** xác nhận worker đang trao đổi được với nguồn. Sự kiện phát hiện người và xâm nhập phụ thuộc chủ đề do firmware phát ra. Nếu máy nhận được luồng RTSP nhưng ONVIF thiếu các sự kiện cần thiết hoặc phát chủ đề chưa nhận dạng, dùng Frigate.

## 4. Dùng Frigate khi chỉ có RTSP

Cài [Frigate](https://docs.frigate.video/guides/getting_started/) và một MQTT broker trên máy trong mạng nội bộ. Mô hình phát hiện người chạy tại chỗ. Ví dụ cấu hình tối thiểu cho một camera trong Frigate:

```yaml
mqtt:
  enabled: true
  host: mosquitto
  topic_prefix: frigate
detect:
  enabled: true
  fps: 5
objects:
  track: [person]
snapshots:
  enabled: true
cameras:
  imou_san:
    ffmpeg:
      inputs:
        - path: rtsp://USER:PASSWORD@192.168.1.25:554/PATH_DA_XAC_MINH
          roles: [detect]
    zones:
      san_truoc:
        coordinates: 0.1,0.4,0.9,0.4,0.9,0.95,0.1,0.95
```

Đổi địa chỉ MQTT, thông tin RTSP và vùng theo mạng của bạn. Tạo camera nguồn **Frigate cục bộ** với tên `imou_san` và vùng xâm nhập `san_truoc`. Khi một người đi vào vùng, worker ghi cảnh báo xâm nhập. Để thử chuyển động, tạo chuyển động trong khung hình và xem sự kiện riêng mà Frigate gửi.

Trong `server/.env`, điền `FRIGATE_MQTT_HOST`, cổng và thông tin xác thực MQTT. Đặt `FRIGATE_URL` tới API Frigate nội bộ, ví dụ `http://127.0.0.1:5000` nếu cùng máy. Giữ cổng API nội bộ của Frigate trong mạng tin cậy. Nếu các thành phần chạy bằng container, thay `127.0.0.1` bằng địa chỉ dịch vụ mà worker truy cập được. Ảnh người có thể xuất hiện sau khi Frigate hoàn tất theo dõi sự kiện.

## 5. Email và vận hành

- Điền `SMTP_HOST`, `SMTP_PORT`, `SMTP_MODE`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` trong `server/.env`. Dùng `SMTP_MODE=starttls` cho cổng 587 hoặc `ssl` cho cổng 465 theo cấu hình nhà cung cấp. Đặt `APP_URL` thành địa chỉ web mà người dùng mở được từ email.
- Khi phục vụ người dùng qua HTTPS, đặt `COOKIE_SECURE=true`. Có thể chạy `npm run build` và `npm start` sau reverse proxy HTTPS. Nếu API đổi địa chỉ, đặt `CAMERA_API_URL` trong `client/.env.local` trước khi build.
- Giữ worker chạy trong suốt thời gian cần giám sát. Worker lưu ảnh JPEG tối đa 2 MB vào PostgreSQL và dọn dữ liệu cũ mặc định sau 30 ngày. Đổi bằng `ALERT_RETENTION_DAYS`. Nếu nguồn sự kiện chưa trả được ảnh, giao diện hiển thị **Chưa có ảnh**.
- Có thể tắt camera để giữ lịch sử. Xóa camera cũng xóa lịch sử, ảnh và quyền xem thuộc camera đó.

## 6. Camera ở xa qua Imou Cloud

Dùng nguồn này khi chủ camera có thể cấp quyền từ Imou Life và máy chạy worker không vào được mạng LAN của camera. Bản tích hợp hỗ trợ **phát hiện người** và ảnh do Imou trả về. Cấu hình dùng một tài khoản Imou Life đã ủy quyền cho các camera nguồn Imou Cloud.

### Nhận mã ủy quyền

1. Mở [Imou Open Platform](https://open.imoulife.com/) và vào **Console → OAuth**. Tạo dự án OAuth. Imou yêu cầu một **Callback URL after authorization** và có bước xét duyệt. Với dự án cần xét duyệt, dùng URL HTTPS ổn định để địa chỉ còn truy cập được khi dự án được duyệt.
2. Nếu chưa có endpoint nhận mã, chạy chương trình thử bên dưới từ `server/`. Hai dòng tạo đường dẫn ngẫu nhiên và chạy chương trình trên PowerShell. Giữ đường dẫn này để cấu hình lại khi cần.

   ```powershell
   $path = "/" + (python -c "import secrets; print(secrets.token_urlsafe(24))")
   $path
   python imou_callback.py --path $path
   ```

3. Trỏ reverse proxy HTTPS vào `127.0.0.1:8765` cho đúng đường dẫn vừa tạo. Khi thử ngắn hạn có thể mở một terminal khác và chạy `cloudflared tunnel --url http://127.0.0.1:8765`. Ghép hostname HTTPS với đường dẫn để điền vào Console. URL Quick Tunnel đổi khi khởi động lại. Chỉ trỏ tunnel vào chương trình nhận mã dùng thử, giữ kín đường dẫn và dừng chương trình sau khi nhận mã.
4. Sau khi dự án được duyệt, lấy **Project Access Key**, **Project Secret Key** và **User Authorization H5 Page** trong mục OAuth. Lấy **Data Center** trong **Console → My information**, dùng mã vùng, không dùng toàn bộ hostname.
5. Chủ camera mở **User Authorization H5 Page**, đăng nhập Imou Life và xác nhận ủy quyền. Terminal chạy chương trình thử sẽ in mã OAuth. Dùng mã ngay ở bước cấu hình bên dưới. Nếu bạn được chia sẻ camera, hãy nhờ tài khoản chủ thiết bị thực hiện thao tác cấp quyền.

### Cấu hình server và thêm camera

Điền `IMOU_DATA_CENTER`, `IMOU_PROJECT_ACCESS_KEY` và `IMOU_PROJECT_SECRET_KEY` trong `server/.env`. Giữ `CAMERA_SECRET_KEY` đã dùng trước đây để mã hóa token. `IMOU_DEVICE_TIMEZONE` phải khớp múi giờ camera và mặc định là `Asia/Ho_Chi_Minh`. `IMOU_POLL_SECONDS` mặc định 300 giây, phạm vi 60–600 giây. Kiểm tra hạn mức trong [bảng giá Imou](https://open.imoulife.com/price) trước khi tăng tần suất hoặc số camera.

Sau khi sao lưu DB hiện tại, dừng API và worker rồi chạy từ `server/` bằng Python trong môi trường ảo. Lệnh schema bổ sung cột và bảng OAuth cho DB đang chạy phiên bản trước.

```powershell
.\.venv\Scripts\python.exe manage.py schema
.\.venv\Scripts\python.exe manage.py imou-authorize --callback "https://HOST/DUONG-DAN"
```

Nhập mã khi được hỏi. Token được mã hóa trong PostgreSQL và worker tự làm mới access token. Khi Imou yêu cầu cấp quyền lại, mở lại luồng ủy quyền rồi chạy lại `imou-authorize`. Nếu thay sang tài khoản Imou Life khác, tất cả camera Imou Cloud sẽ dùng quyền mới.

Khởi động API và client. Trên web, vào **Camera → Thêm camera → Imou Cloud**, nhập số serial và kênh camera (thường thử `0` trước trên camera một kênh), rồi lưu. Cấp camera cho người dùng nếu cần. Để thử một sự kiện có sẵn trong Imou Life, lấy ID trên web và chạy từ `server/`:

```powershell
.\.venv\Scripts\python.exe manage.py imou-check 1 --minutes 120
```

Thay `1` bằng ID thật. Nếu trả về **JPEG OK**, API đã trả sự kiện người và tải được ảnh. Nếu API từ chối, kiểm tra quyền OAuth của tài khoản chủ camera với Imou. Nếu có sự kiện nhưng thiếu ảnh, thử một sự kiện khác trong Imou Life. Chẩn đoán này chỉ đọc Imou và không tạo cảnh báo trong DB.

Bật lại `worker.py` để nhận cảnh báo theo lịch của người dùng. Worker truy vấn lịch sử và dùng giờ xảy ra sự kiện để xét lịch 22:00–06:00. Thời gian hiện cảnh báo phụ thuộc chu kỳ truy vấn và lúc Imou trả sự kiện. Có thể tạm đặt lịch cả ngày để thử bằng một sự kiện mới. Nguồn Imou Cloud trong phiên bản này đọc sự kiện người qua truy vấn lịch sử.

Tài liệu Imou: [OAuth](https://open.imoulife.com/book/02-concepts/04.oauth-authorization.html) · [Lịch sử cảnh báo](https://open.imoulife.com/book/04-capabilities/06.alarm-messages/03-message-search.html) · [Sự kiện người](https://open.imoulife.com/book/04-capabilities/detection/person/detected.html).
