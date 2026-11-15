# Camera Alert

```text
camera-alert/
├── client/   Next.js App Router và TypeScript
├── server/   FastAPI và SQLite
└── README.md
```

## Chạy trên máy tính

Cần Node.js 20.9 trở lên và Python 3.11 trở lên. Mở hai terminal tại thư mục `camera-alert`.

Terminal 1

```bash
cd server
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Nếu dùng Windows PowerShell, thay dòng `source` bằng
`.\.venv\Scripts\Activate.ps1`.

Terminal 2

```bash
cd client
npm install
npm run dev
```

Mở [trang cảnh báo](http://127.0.0.1:3000) hoặc [tài liệu API](http://127.0.0.1:8000/docs).
Cả hai ứng dụng mặc định chỉ lắng nghe trên máy đang chạy.

## Thử luồng cảnh báo

1. Giữ lịch mặc định 22:00–06:00. Lịch tính theo giờ Việt Nam và áp dụng trên mọi loại sự kiện.
2. Gửi sự kiện **Phát hiện người** với giờ thử 23:00. Cảnh báo xuất hiện trong lịch sử.
3. Gửi lại với giờ thử 12:00. Server bỏ qua sự kiện và lịch sử giữ nguyên.
4. Đổi lịch và nhấn **Lưu khung giờ** trước khi thử tiếp.

Mốc bắt đầu được tính vào khung giờ và mốc kết thúc nằm ngoài khung giờ.
Hai mốc bằng nhau tương ứng với 24 giờ. Server lưu lịch và cảnh báo trong
`server/data/camera.db`. Web hiển thị tối đa 50 cảnh báo được lưu gần nhất.

## Cấu hình tùy chọn

| Biến | Vị trí | Công dụng |
| --- | --- | --- |
| `CAMERA_API_URL` | `client/.env.local` | Địa chỉ Python API nếu đổi cổng hoặc host, mặc định `http://127.0.0.1:8000` |
| `CAMERA_DB_PATH` | Môi trường của tiến trình Python | Đường dẫn tệp SQLite nếu cần lưu ở vị trí khác |

Bản này chỉ dùng sự kiện mô phỏng. Tích hợp IMOU, chụp ảnh, quản lý nhiều camera
và xác thực là các phần triển khai tiếp theo. Dữ liệu mô phỏng được ghi vào
SQLite cùng lịch sử hiển thị để thử luồng lưu và đọc dữ liệu.
