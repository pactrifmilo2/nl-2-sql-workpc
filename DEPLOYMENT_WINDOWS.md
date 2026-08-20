# Hướng dẫn triển khai production trên Windows

## Cách đơn giản dành cho vận hành

Repository đã có bộ script tự động trong thư mục `deployment`. Đây là cách nên
dùng; các phần phía dưới được giữ làm tài liệu kỹ thuật và xử lý sự cố.

Trên máy phát triển, Double-click `deployment\BUILD.cmd`. Version được đọc trực
tiếp từ `pyproject.toml`; phải tăng version trước mỗi release mới.

Mặc định, release có sẵn `uv.exe` và toàn bộ Python dependency để production
không cần Internet khi deploy. Script chạy test, build wheel, tải và kiểm tra
checksum WinSW, rồi tạo:

```text
release-output\nl2sql-x.y.z.zip
release-output\nl2sql-x.y.z.zip.sha256
```

Người vận hành production chỉ cần:

1. Copy ZIP sang production và giải nén vào một thư mục mới.
2. Double-click `DEPLOY.cmd`, chấp nhận quyền Administrator.
3. Chờ dòng `DEPLOYMENT SUCCESSFUL`.
4. Double-click `CHECK.cmd`; kết quả phải là `RESULT : OK`.

Lần đầu trên một máy mới, script tạo `C:\Apps\nl2sql\.env`, mở Notepad và dừng
để người kỹ thuật cấu hình. Sau khi cấu hình xong, chạy lại `DEPLOY.cmd`. Các lần
nâng cấp tiếp theo không sửa hoặc ghi đè `.env`, `data`, ChromaDB hay log.

Hướng dẫn cực ngắn cho người vận hành nằm trong file `README-VI.txt` của mỗi ZIP.
Không cần cài Git và không cần clone/pull code trên production.

Tài liệu này hướng dẫn đóng gói và triển khai **nl-2-sql-vanna-oracle-pc** lên
một máy Windows production dưới dạng Windows Service. Máy production không cần
cài Git và không cần clone/pull source code.

Giải pháp được sử dụng:

1. Máy phát triển build ứng dụng thành Python wheel (`.whl`).
2. Chuyển một gói release ZIP sang máy production.
3. Cài wheel vào virtual environment riêng.
4. Dùng WinSW để chạy Uvicorn dưới dạng Windows Service.
5. Để `.env`, ChromaDB và log bên ngoài wheel để có thể nâng cấp mà không mất dữ
   liệu.

> Wheel là gói cài đặt, giúp máy production không cần repository. Tuy nhiên,
> wheel Python không phải là cơ chế mã hóa hoặc bảo vệ source code khỏi quản trị
> viên của máy production.

## 1. Điều kiện và giả định

Hướng dẫn giả định:

- Máy build và máy production đều là Windows x64.
- Ứng dụng dùng CPython **3.14.6** trên production.
- Oracle đã cho phép máy production kết nối đến database.
- Ollama chạy trên máy production hoặc có một Ollama server từ xa.
- Ứng dụng lắng nghe tại cổng `8000`.
- Chỉ chạy **một Uvicorn worker** vì conversation store hiện tại nằm trong bộ
  nhớ của process.

Các thành phần cần có trên máy production:

- CPython 3.14.6 x64 từ Python.org;
- uv 0.11.32 để tạo môi trường và cài dependency đã khóa;
- WinSW x64;
- kết nối mạng đến Oracle;
- kết nối đến Ollama và model đã được tải;
- quyền mở cổng ứng dụng trong Windows Firewall nếu máy khác cần truy cập.

### Kết quả kiểm thử runtime ngày 05/08/2026

Wheel và toàn bộ dependency trong `uv.lock` đã được cài vào ba môi trường Windows
x64 sạch. Mỗi môi trường được kiểm tra import ChromaDB, `oracledb`, pandas và
Vanna, khởi tạo FastAPI app, sau đó chạy toàn bộ test hiện có:

| Runtime | Cài dependency | Khởi tạo app | Test |
|---|---:|---:|---:|
| CPython 3.12.13 | Đạt | Đạt, 12 route | 13 passed |
| CPython 3.13.14 | Đạt | Đạt, 12 route | 13 passed |
| CPython 3.14.6 | Đạt | Đạt, 12 route | 13 passed |

Cảnh báo duy nhất là Vanna còn dùng Pydantic class-based config đã deprecated;
đây không phải lỗi tương thích Python 3.14. Vì 3.14.6 có binary Windows chính
thức, vẫn đang trong giai đoạn bugfix và được hỗ trợ bảo mật đến khoảng tháng
10/2030, tài liệu chọn 3.14.6 làm runtime production. Vẫn phải chạy staging với
Oracle và Ollama thật trước khi go-live vì test tự động không kết nối hai hệ thống
này.

## 2. Kiến trúc thư mục production

Sử dụng một thư mục cố định, ví dụ:

```text
C:\Apps\nl2sql\
├── .venv\                 # Python virtual environment
├── app\                   # Wheel của ứng dụng
├── data\
│   └── chroma_db\         # Bộ nhớ ChromaDB cần sao lưu
├── logs\                  # Log của ứng dụng
├── service-logs\          # stdout/stderr và log của WinSW
├── .env                    # Cấu hình và secrets production
├── requirements.txt       # Phiên bản dependency khóa từ uv.lock
├── nl2sql-service.exe      # WinSW được đổi tên
└── nl2sql-service.xml      # Cấu hình Windows Service
```

Không đặt `.env`, `data` hoặc `logs` bên trong `.venv` hay `app`. Những thư mục
này phải tồn tại độc lập để nâng cấp wheel không làm mất dữ liệu.

## 3. Chuẩn bị release trên máy phát triển

### 3.1. Kiểm tra trước khi build

Từ thư mục repository:

```powershell
Set-Location "D:\Coding projects\nl-2-sql-workpc"

git status --short
uv sync --frozen
```

Xác nhận các thay đổi chưa commit đúng là những thay đổi cần đưa lên production.
Nên tăng `version` trong `pyproject.toml` cho mỗi release, ví dụ từ `0.1.0` lên
`0.1.1`, để việc nâng cấp và rollback rõ ràng.

Không đưa file `.env` thật vào release. Chỉ đưa `.env.oracle.example`, sau đó tạo
`.env` trực tiếp trên máy production bằng kênh chuyển secrets an toàn.

### 3.2. Build wheel và dependency manifest

Thay giá trị version cho phù hợp:

```powershell
$Version = "0.1.0"
$ReleaseRoot = "D:\releases\nl2sql-$Version"

New-Item -ItemType Directory -Force "$ReleaseRoot\app"

uv build `
  --wheel `
  --no-sources `
  --out-dir "$ReleaseRoot\app"

uv export `
  --frozen `
  --no-dev `
  --no-emit-project `
  --format requirements.txt `
  --output-file "$ReleaseRoot\requirements.txt"

Copy-Item .env.oracle.example "$ReleaseRoot\.env.example"
```

Kiểm tra wheel có chứa UI template và static assets:

```powershell
$Wheel = (Get-ChildItem "$ReleaseRoot\app\*.whl").FullName
uv run python -m zipfile -l $Wheel | Select-String "ui/"
```

Kết quả cần có các file như `ui/templates/index.html` và
`ui/static/voice-input.js`.

### 3.3. Tạo release ZIP

```powershell
Compress-Archive `
  -Path "$ReleaseRoot\*" `
  -DestinationPath "D:\releases\nl2sql-$Version.zip" `
  -Force
```

Chuyển file ZIP này đến máy production qua kênh nội bộ được phê duyệt.

### 3.4. Tùy chọn: chuẩn bị dependency cho máy không có Internet

Thực hiện bước này trên máy Windows x64 dùng cùng CPython 3.14.6 với
production:

```powershell
New-Item -ItemType Directory -Force "$ReleaseRoot\wheelhouse"

uv run --with pip python -m pip download `
  --only-binary=:all: `
  --requirement "$ReleaseRoot\requirements.txt" `
  --dest "$ReleaseRoot\wheelhouse"
```

Sau đó tạo lại ZIP. Nếu một dependency không có wheel tương thích, lệnh sẽ báo
lỗi; không nên âm thầm build native dependency trên một nền tảng khác production.

Máy production offline cần nhận bộ cài CPython 3.14.6 x64 chính thức, `uv.exe`,
wheel của ứng dụng và toàn bộ `wheelhouse` qua kho phần mềm nội bộ đã được phê
duyệt.

## 4. Chuẩn bị máy production

### 4.1. Tạo thư mục và giải nén

Mở PowerShell với quyền Administrator:

```powershell
New-Item -ItemType Directory -Force "C:\Apps\nl2sql"
Expand-Archive `
  -Path "C:\Temp\nl2sql-0.1.0.zip" `
  -DestinationPath "C:\Apps\nl2sql" `
  -Force

Set-Location "C:\Apps\nl2sql"
New-Item -ItemType Directory -Force data, logs, service-logs
```

Không copy `.venv` từ máy build. Virtual environment có đường dẫn nội bộ và nên
được tạo mới trên chính máy production.

### 4.2. Cài đúng CPython 3.14.6

Python 3.14.6 phát hành ngày 10/06/2026 và có Windows installer x64 chính thức.
Tải từ trang release của Python.org hoặc cài bằng Python Install Manager của
Python.org:

```powershell
winget install 9NQ7512CXL7T
py install 3.14.6
py -V:3.14 --version
```

Kết quả phải là `Python 3.14.6`. Nếu policy production không cho dùng Microsoft
Store/WinGet, tải `python-3.14.6-amd64.exe` trực tiếp từ trang release chính thức,
xác minh checksum/Sigstore theo quy định nội bộ và cài cho máy.

Sau đó cài hoặc cập nhật **uv 0.11.32** bằng kênh nội bộ được phê duyệt và kiểm
tra bằng `uv --version`. Không phụ thuộc vào uv cũ trên máy build: bản uv 0.9.11
của môi trường phát triển hiện tại đã cũ; các kiểm thử ma trận được chạy bằng uv
0.11.32.

Python 3.12.13 vẫn chạy được ứng dụng, nhưng Python.org chỉ phát hành source và
không cung cấp Windows binary chính thức cho bản này. Chỉ dùng 3.12.13 nếu tổ
chức đã phê duyệt bản dựng `python-build-standalone` do uv quản lý.

### 4.3. Tạo virtual environment và cài ứng dụng

```powershell
Set-Location "C:\Apps\nl2sql"

uv venv --python 3.14.6 .venv

uv pip install `
  --python .\.venv\Scripts\python.exe `
  --requirement .\requirements.txt

$Wheel = (Get-ChildItem .\app\*.whl).FullName

uv pip install `
  --python .\.venv\Scripts\python.exe `
  --no-deps `
  $Wheel
```

Nếu production không có Internet và release có `wheelhouse`:

```powershell
uv pip install `
  --python .\.venv\Scripts\python.exe `
  --no-index `
  --find-links .\wheelhouse `
  --requirement .\requirements.txt

$Wheel = (Get-ChildItem .\app\*.whl).FullName

uv pip install `
  --python .\.venv\Scripts\python.exe `
  --no-deps `
  $Wheel
```

Kiểm tra import:

```powershell
.\.venv\Scripts\python.exe -c "import nl_2_sql_vanna_oracle_pc; print('Import OK')"
.\.venv\Scripts\python.exe --version
```

Kết quả version phải là `Python 3.14.6`.

## 5. Tạo cấu hình `.env` production

```powershell
Copy-Item .env.example .env
notepad .env
```

Cấu hình tối thiểu tham khảo:

```dotenv
# Ollama
OLLAMA_MODEL=qwen2.5-coder:latest
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_BASIC_AUTH_USER=
OLLAMA_BASIC_AUTH_PASSWORD=

# Oracle
ORACLE_USER=production_readonly_user
ORACLE_PASSWORD=replace-with-secret
ORACLE_DSN=192.168.0.1:1521/PDBORCL

# ChromaDB
CHROMA_PERSIST_DIRECTORY=./data/chroma_db
CHROMA_COLLECTION_NAME=atfm-oracle

# SQL scope
ALLOWED_TABLES=T_FINISHED_FLIGHTS,T_DAY_FLIGHTS

# Bảo vệ web application
APP_BASIC_AUTH_USER=nl2sql-user
APP_BASIC_AUTH_PASSWORD=replace-with-strong-secret

# Report API
REPORT_API_KEY=replace-with-separate-strong-secret

# Log
LOG_LEVEL=INFO
LOG_FILE=./logs/app.log
AUDIT_LOG_FILE=./logs/audit.jsonl
HITL_FEEDBACK_LOG_FILE=./logs/feedback.jsonl
AI_REPORT_LOG_FILE=./logs/ai_report.jsonl

# HITL
HITL_ENABLED=true
```

Yêu cầu bảo mật:

- Oracle user chỉ nên có quyền đọc các bảng được cho phép.
- Không gửi `.env` qua email hoặc commit vào Git.
- Chỉ tài khoản service và Administrators được đọc `.env`.
- Không dùng chung `APP_BASIC_AUTH_PASSWORD` và `REPORT_API_KEY`.
- Nếu public ra Internet, đặt ứng dụng sau HTTPS reverse proxy; không expose trực
  tiếp HTTP cổng 8000.

## 6. Chuẩn bị Ollama

Nếu Ollama chạy trên cùng máy:

```powershell
ollama pull qwen2.5-coder:latest
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Ollama phải tiếp tục chạy khi không có người dùng đăng nhập. Không phụ thuộc vào
một cửa sổ terminal hoặc tray application của user. Có thể chạy Ollama dưới dạng
service riêng, hoặc dùng một Ollama server từ xa đã được vận hành ổn định.

Nếu dùng Ollama từ xa, cập nhật `OLLAMA_HOST` và kiểm tra firewall, proxy, TLS và
Basic Auth trước khi khởi động ứng dụng.

## 7. Kiểm tra kết nối Oracle

Kiểm tra cổng database:

```powershell
Test-NetConnection 192.168.0.1 -Port 1521
```

Nếu kiểm tra thất bại, xử lý route, VPN, DNS hoặc firewall trước. Ứng dụng hiện
dùng `oracledb` qua `OracleRunner` và không gọi `init_oracle_client`, nên mặc định
chạy ở Oracle Thin mode; thông thường không cần cài Oracle Instant Client.

## 8. Khởi tạo hoặc chuyển ChromaDB

### Trường hợp triển khai mới

Chạy seed một lần, từ đúng thư mục chứa `.env`:

```powershell
Set-Location "C:\Apps\nl2sql"
.\.venv\Scripts\python.exe -m nl_2_sql_vanna_oracle_pc.training
```

Lệnh training upsert các baseline memory bằng ID ổn định và giữ nguyên các memory
đã được admin phê duyệt. Có thể chạy lại sau khi nâng cấp training data/schema.

### Trường hợp chuyển dữ liệu từ máy cũ

1. Dừng ứng dụng trên máy cũ.
2. Dừng service trên máy mới nếu đang chạy.
3. Copy toàn bộ thư mục `chroma_db` cũ vào
   `C:\Apps\nl2sql\data\chroma_db`.
4. Giữ nguyên `CHROMA_COLLECTION_NAME`.
5. Không chạy module `training` sau khi copy, nếu muốn giữ các mẫu đã được admin
   phê duyệt từ chat.

Không copy ChromaDB trong lúc process đang ghi dữ liệu.

## 9. Chạy thử bằng console

Trước khi cài service, luôn chạy thử bằng đúng executable, working directory và
`.env` production:

```powershell
Set-Location "C:\Apps\nl2sql"

.\.venv\Scripts\python.exe `
  -m uvicorn nl_2_sql_vanna_oracle_pc.asgi:app `
  --host 0.0.0.0 `
  --port 8000 `
  --workers 1
```

Không thêm `--reload` trên production.

Từ một PowerShell khác:

```powershell
Invoke-WebRequest http://127.0.0.1:8000 -UseBasicParsing
```

Nếu đã bật Basic Auth, mã `401` khi không gửi credential là hành vi đúng. Kiểm
tra thêm bằng browser với tài khoản đã cấu hình.

Sau đó thử một câu hỏi tiếng Việt có truy vấn flight data và xác nhận:

- UI tải được;
- Ollama trả lời;
- agent gọi `run_sql`;
- Oracle trả kết quả;
- có log trong `logs`;
- HITL hiện nút phản hồi nếu `HITL_ENABLED=true`.

Nhấn `Ctrl+C` để dừng console trước khi cài service.

## 10. Cài WinSW Windows Service

### 10.1. Chuẩn bị WinSW

Pin **WinSW v2.12.0 x64**, là bản stable/latest hiện tại. Không dùng
`v3.0.0-alpha.11` cho production chỉ vì số phiên bản cao hơn; nhánh v3 vẫn được
đánh dấu pre-release và có thay đổi không tương thích với v2.

Tải `WinSW-x64.exe` từ release v2.12.0 chính thức và lưu vào:

```text
C:\Apps\nl2sql\nl2sql-service.exe
```

Tên file XML phải trùng với tên executable:

```text
C:\Apps\nl2sql\nl2sql-service.xml
```

### 10.2. Nội dung `nl2sql-service.xml`

```xml
<service>
  <id>Nl2SqlVannaOracle</id>
  <name>NL2SQL Vanna Oracle</name>
  <description>Vietnamese natural-language to Oracle SQL service</description>

  <executable>%BASE%\.venv\Scripts\python.exe</executable>
  <arguments>-m uvicorn nl_2_sql_vanna_oracle_pc.asgi:app --host 0.0.0.0 --port 8000 --workers 1</arguments>
  <workingdirectory>%BASE%</workingdirectory>

  <startmode>Automatic</startmode>
  <delayedAutoStart/>
  <stoptimeout>30 sec</stoptimeout>
  <stopparentprocessfirst>true</stopparentprocessfirst>

  <env name="PYTHONUNBUFFERED" value="1"/>

  <onfailure action="restart" delay="10 sec"/>
  <onfailure action="restart" delay="30 sec"/>

  <logpath>%BASE%\service-logs</logpath>
  <log mode="roll"/>
</service>
```

XML trên dùng cú pháp của WinSW v2.12.0. `workingdirectory` rất quan trọng vì
`.env`, ChromaDB và log đang dùng đường dẫn tương đối. `%BASE%` là thư mục chứa
WinSW executable. `stopparentprocessfirst` giúp gửi Ctrl+C đến Uvicorn trước để
process có thời gian shutdown sạch; sau 30 giây WinSW mới buộc dừng nếu process
không thoát.

### 10.3. Cài và khởi động service

Mở PowerShell bằng **Run as Administrator**:

```powershell
Set-Location "C:\Apps\nl2sql"

.\nl2sql-service.exe install
.\nl2sql-service.exe start
.\nl2sql-service.exe status

Get-Service Nl2SqlVannaOracle
```

Nếu service không start, kiểm tra:

```powershell
Get-ChildItem .\service-logs
Get-Content .\logs\app.log -Tail 100
```

Kiểm tra thêm Windows Event Viewer và file `*.wrapper.log` trong
`service-logs`.

## 11. Tài khoản chạy service và quyền thư mục

Không nên vận hành ứng dụng lâu dài bằng tài khoản Administrator cá nhân.

Khuyến nghị tạo tài khoản service riêng, ví dụ:

```text
DOMAIN\svc_nl2sql
```

Sau khi cài service:

1. Mở `services.msc`.
2. Chọn **NL2SQL Vanna Oracle**.
3. Mở **Properties → Log On**.
4. Chọn **This account** và nhập tài khoản service.
5. Cấp quyền **Log on as a service** nếu chính sách máy yêu cầu.
6. Restart service.

Quyền tối thiểu:

- Read & Execute: `C:\Apps\nl2sql`, `.venv`, `app`;
- Read: `.env`;
- Modify: `data`, `logs`, `service-logs`;
- quyền kết nối đến Oracle và Ollama qua mạng.

Sau khi thay đổi tài khoản, chạy lại smoke test dưới chính tài khoản đó nếu có
thể. Service account có `PATH`, proxy và quyền mạng khác với user tương tác.

## 12. Firewall và truy cập từ máy khác

Chỉ mở cổng cho mạng hoặc IP cần thiết. Ví dụ sau chỉ mang tính tham khảo; thay
dải mạng theo hệ thống thực tế:

```powershell
New-NetFirewallRule `
  -DisplayName "NL2SQL TCP 8000 - Internal" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8000 `
  -RemoteAddress 192.168.0.0/16 `
  -Action Allow
```

Không tạo rule `Any` nếu ứng dụng chỉ dùng nội bộ. Với triển khai Internet, dùng
IIS, Nginx hoặc reverse proxy tương đương để terminate HTTPS, sau đó chỉ cho proxy
truy cập cổng 8000.

Vanna web component chính đã được đóng gói trong wheel, nên chat và bảng kết quả
hoạt động khi browser không có Internet. Một số visualization tùy chọn vẫn có thể
dùng D3, Plotly, Three.js hoặc map tiles từ URL ngoài; các phần đó cần được
vendoring riêng nếu production phải air-gapped hoàn toàn.

## 13. Kiểm tra sau khi cài service

```powershell
Get-Service Nl2SqlVannaOracle
Invoke-WebRequest http://127.0.0.1:8000 -UseBasicParsing
Get-Content C:\Apps\nl2sql\logs\app.log -Tail 100
```

Checklist nghiệm thu:

- [ ] Service ở trạng thái `Running`.
- [ ] Service tự chạy lại sau khi reboot.
- [ ] Trang web truy cập được từ subnet cho phép.
- [ ] Truy cập không credential bị từ chối nếu bật Basic Auth.
- [ ] Ollama model đúng với `OLLAMA_MODEL`.
- [ ] Oracle query chạy bằng user read-only.
- [ ] SQL chỉ dùng bảng/cột trong allowlist.
- [ ] ChromaDB ghi vào `data/chroma_db`.
- [ ] Application log, audit log và report log được tạo.
- [ ] HITL lưu feedback đúng quyền admin/guest.
- [ ] WinSW restart service sau một lần process lỗi thử nghiệm có kiểm soát.
- [ ] Đã cấu hình lịch backup.

## 14. Sao lưu

Các dữ liệu cần sao lưu:

- `.env` bằng cơ chế lưu secrets an toàn;
- toàn bộ `data/chroma_db`;
- `logs/feedback.jsonl`;
- `logs/ai_report.jsonl` nếu cần lưu lịch sử report;
- `logs/audit.jsonl` theo chính sách audit;
- release ZIP và wheel đang chạy.

Để có bản sao ChromaDB nhất quán:

```powershell
Set-Location "C:\Apps\nl2sql"
.\nl2sql-service.exe stop

Compress-Archive `
  -Path .\data\chroma_db\* `
  -DestinationPath "D:\Backups\nl2sql-chroma-$(Get-Date -Format yyyyMMdd-HHmmss).zip"

.\nl2sql-service.exe start
```

Không lưu file backup chung ổ đĩa duy nhất với ứng dụng. Kiểm tra phục hồi định kỳ,
không chỉ kiểm tra việc tạo file backup.

## 15. Nâng cấp phiên bản

1. Build release mới với version mới.
2. Chuyển release ZIP mới đến production.
3. Sao lưu `.env` và `data/chroma_db`.
4. Dừng service.
5. Cài dependency và wheel mới.
6. Không chạy training trừ khi chủ động reset Chroma collection.
7. Khởi động service và chạy smoke test.

Ví dụ:

```powershell
Set-Location "C:\Apps\nl2sql"
.\nl2sql-service.exe stop

uv pip install `
  --python .\.venv\Scripts\python.exe `
  --upgrade `
  --requirement .\requirements-new.txt

uv pip install `
  --python .\.venv\Scripts\python.exe `
  --upgrade `
  --no-deps `
  .\app\nl_2_sql_vanna_oracle_pc-0.1.1-py3-none-any.whl

.\nl2sql-service.exe start
.\nl2sql-service.exe status
```

Nếu không tăng version, `pip` có thể không thay thế wheel đang cài; khi đó phải
dùng `--force-reinstall`. Tăng version cho mỗi release là phương án sạch hơn.

## 16. Rollback

Luôn giữ lại:

- wheel phiên bản trước;
- `requirements.txt` của phiên bản trước;
- backup ChromaDB trước nâng cấp;
- bản `.env` đang hoạt động.

Rollback:

1. Dừng service.
2. Cài lại dependency manifest và wheel phiên bản trước.
3. Chỉ restore ChromaDB nếu migration hoặc thao tác của phiên bản mới đã làm thay
   đổi dữ liệu không tương thích.
4. Start service và chạy lại smoke test.

```powershell
.\nl2sql-service.exe stop

uv pip install `
  --python .\.venv\Scripts\python.exe `
  --force-reinstall `
  --requirement .\rollback\requirements.txt

uv pip install `
  --python .\.venv\Scripts\python.exe `
  --force-reinstall `
  --no-deps `
  .\rollback\nl_2_sql_vanna_oracle_pc-0.1.0-py3-none-any.whl

.\nl2sql-service.exe start
```

## 17. Gỡ service

Gỡ đăng ký service nhưng giữ dữ liệu:

```powershell
Set-Location "C:\Apps\nl2sql"
.\nl2sql-service.exe stop
.\nl2sql-service.exe uninstall
```

Không xóa `.env`, `data/chroma_db` hoặc log cho đến khi đã xác nhận backup và hết
thời hạn lưu trữ cần thiết.

## 18. Xử lý lỗi thường gặp

### Service start rồi dừng ngay

Kiểm tra theo thứ tự:

1. `service-logs\*.wrapper.log`;
2. stdout/stderr trong `service-logs`;
3. `logs\app.log`;
4. Windows Event Viewer;
5. chạy chính command Uvicorn bằng console từ `C:\Apps\nl2sql`.

Nguyên nhân thường gặp: sai đường dẫn Python, `.env` không được tìm thấy, service
account không có quyền đọc `.env` hoặc ghi log/ChromaDB.

### Không kết nối được Ollama

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Kiểm tra `OLLAMA_HOST`, model, firewall, proxy và việc Ollama có chạy khi không có
user đăng nhập hay không.

### Không kết nối được Oracle

```powershell
Test-NetConnection <oracle-host> -Port 1521
```

Kiểm tra DSN, service name, credential, VPN, DNS, route, firewall và quyền DB.

### UI mở được nhưng thiếu component chat

Kiểm tra request `/static/vanna-components.js` trong Developer Tools của browser
và xác nhận wheel đang chạy có chứa file này. Component chat chính được phục vụ
từ local static assets, không tải từ `img.vanna.ai`.

### ChromaDB trống hoặc query retrieval cũ

- Xác nhận `CHROMA_PERSIST_DIRECTORY` trỏ đúng `data/chroma_db`.
- Xác nhận service account có quyền Modify.
- Xác nhận `CHROMA_COLLECTION_NAME` không bị đổi.
- Chạy lại module training để upsert baseline và đồng bộ memory đã duyệt; thao tác
  này không xóa các memory do admin phê duyệt.

## 19. Tài liệu tham khảo

- uv build: <https://docs.astral.sh/uv/concepts/projects/build/>
- uv package guide: <https://docs.astral.sh/uv/guides/package/>
- Python 3.12.13: <https://www.python.org/downloads/release/python-31213/>
- Python 3.14.6: <https://www.python.org/downloads/release/python-3146/>
- Lịch hỗ trợ Python 3.14: <https://peps.python.org/pep-0745/>
- Python Install Manager:
  <https://www.python.org/downloads/release/pymanager-263/>
- uv Python management: <https://docs.astral.sh/uv/guides/install-python/>
- uv 0.11.32: <https://github.com/astral-sh/uv/releases/tag/0.11.32>
- WinSW v2.12.0 stable:
  <https://github.com/winsw/winsw/releases/tag/v2.12.0>
- WinSW v2.12.0 XML configuration:
  <https://github.com/winsw/winsw/blob/v2.12.0/doc/xmlConfigFile.md>
- WinSW v2.12.0 logging/troubleshooting:
  <https://github.com/winsw/winsw/blob/v2.12.0/doc/loggingAndErrorReporting.md>
