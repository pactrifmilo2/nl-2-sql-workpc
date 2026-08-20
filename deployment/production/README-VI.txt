TRIỂN KHAI NL2SQL - HƯỚNG DẪN CHO NGƯỜI VẬN HÀNH
=================================================

MỖI LẦN NHẬN PHIÊN BẢN MỚI:

1. Copy file nl2sql-x.y.z.zip vào máy production.
2. Giải nén ZIP vào một thư mục mới.
3. Mở thư mục vừa giải nén và double-click DEPLOY.cmd.
4. Bấm Yes khi Windows hỏi quyền Administrator.
5. Chờ đến khi thấy dòng "DEPLOYMENT SUCCESSFUL" màu xanh.
6. Double-click CHECK.cmd. Kết quả phải là "RESULT : OK".

Không cần Git, không pull source code, không sửa .env khi nâng cấp.
Script sẽ giữ nguyên cấu hình, ChromaDB, database training và logs.

LẦN ĐẦU TIÊN TRÊN MỘT MÁY MỚI:

- DEPLOY.cmd sẽ tạo C:\Apps\nl2sql\.env và mở Notepad.
- Việc điền Oracle/Ollama/admin secret chỉ do người kỹ thuật thực hiện một lần.
- Sau khi người kỹ thuật lưu .env, chạy lại DEPLOY.cmd.

NẾU CÓ LỖI:

- Không xóa C:\Apps\nl2sql.
- Không sửa hoặc gửi file .env cho người không có thẩm quyền.
- Chụp màn hình lỗi và gửi cho người kỹ thuật.
- Có thể chạy CHECK.cmd để lấy trạng thái và các dòng log cuối.
