# Hướng dẫn sử dụng Trợ lí AI

## 1. Giới thiệu

**Trợ lí AI** giúp người dùng tìm kiếm, thống kê và trực quan hóa dữ liệu chuyến bay bằng câu hỏi tiếng Việt. Người dùng không cần biết SQL hoặc cấu trúc cơ sở dữ liệu.

Trợ lí có thể hỗ trợ:

- Liệt kê chuyến bay theo ngày, sân bay đi, sân bay đến hoặc điểm bay qua.
- Tra cứu giờ dự kiến và giờ thực tế của chuyến bay.
- Thống kê số lượng chuyến bay theo các tiêu chí.
- Tạo biểu đồ từ kết quả thống kê.
- Xuất bảng kết quả thành tệp CSV.

> **Lưu ý:** Câu trả lời do AI tạo có thể chưa chính xác trong một số trường hợp. Hãy kiểm tra lại các điều kiện, khoảng thời gian và số liệu trước khi sử dụng cho công việc quan trọng.

## 2. Truy cập hệ thống

1. Mở Chrome hoặc Edge.
2. Truy cập đường dẫn do quản trị viên cung cấp. Khi chạy trên máy cục bộ, địa chỉ mặc định là `http://localhost:8000`.
3. Nếu trình duyệt yêu cầu tên người dùng và mật khẩu, nhập thông tin do quản trị viên cung cấp.
4. Chờ màn hình **Trợ lí AI** và lời chào xuất hiện.

Nếu màn hình hiển thị **Cần cấu hình**, hãy liên hệ quản trị viên. Trợ lí chưa thể truy vấn dữ liệu cho đến khi cấu hình hệ thống hoàn tất.

## 3. Bắt đầu nhanh

1. Nhập câu hỏi vào ô ở cuối cửa sổ trò chuyện.
2. Nhấn **Enter** hoặc chọn nút gửi có biểu tượng mũi tên.
3. Chờ Trợ lí AI xử lý và trả kết quả.
4. Cuộn trong cửa sổ trò chuyện để xem đầy đủ câu trả lời, bảng dữ liệu hoặc biểu đồ.

Nhấn **Shift + Enter** nếu cần xuống dòng mà chưa gửi câu hỏi.

Ví dụ:

> Cho tôi danh sách chuyến bay trong ngày từ VVNB đến VVTH.

## 4. Đặt câu hỏi hiệu quả

Một câu hỏi tốt nên nêu rõ:

- **Việc cần làm:** liệt kê, đếm, thống kê, so sánh hoặc vẽ biểu đồ.
- **Đối tượng:** chuyến bay trong ngày hay chuyến bay đã hoàn thành.
- **Điều kiện:** sân bay đi, sân bay đến, điểm bay qua hoặc số hiệu chuyến bay.
- **Thời gian:** hôm nay, một ngày cụ thể hoặc một khoảng thời gian phù hợp với dữ liệu.
- **Cách trình bày:** bảng, biểu đồ, thứ tự sắp xếp hoặc số dòng cần lấy.

Có thể dùng mẫu sau:

> Hãy **[liệt kê/thống kê/vẽ biểu đồ]** **[dữ liệu cần xem]**, với điều kiện **[điều kiện lọc]**, vào **[thời gian]**, và **[cách sắp xếp/giới hạn kết quả]**.

### Ví dụ câu hỏi

| Nhu cầu | Câu hỏi gợi ý |
|---|---|
| Danh sách chuyến bay | Cho tôi danh sách chuyến bay trong ngày từ VVNB đến VVTH. |
| Chuyến bay đã hoàn thành | Liệt kê các chuyến bay đã hoàn thành đi qua Q1/W2. |
| Tra cứu theo ngày | Cho tôi các chuyến bay ngày 01/01/2025. |
| Tra cứu theo hành trình | Các chuyến bay từ VHHH đến WMKK ngày 01/01/2025. |
| Tra cứu điểm bay qua | Các chuyến bay có điểm bay qua R468. |
| So sánh thời gian | Chuyến bay nào đến SGN muộn hơn giờ dự kiến? |
| Thống kê | Thống kê số chuyến bay theo sân bay đi hôm nay, sắp xếp giảm dần. |
| Giới hạn kết quả | Cho tôi 10 sân bay đến có nhiều chuyến bay nhất hôm nay. |
| Biểu đồ | Vẽ biểu đồ số chuyến bay theo sân bay đi hôm nay. |
| Biểu đồ theo ngày | Vẽ đồ thị số chuyến bay đã hoàn thành theo ngày. |

### Mẹo để có kết quả chính xác hơn

- Dùng mã sân bay chính xác như `VVNB`, `VVTH`, `DAD`, `SGN`, `VHHH` hoặc `WMKK`.
- Ghi ngày đầy đủ, ví dụ `01/01/2025`, để tránh hiểu nhầm.
- Nói rõ **chuyến bay trong ngày** hay **chuyến bay đã hoàn thành**.
- Dùng từ **biểu đồ**, **đồ thị** hoặc **vẽ** khi muốn nhận kết quả trực quan.
- Nếu bảng quá dài, yêu cầu số lượng cụ thể, ví dụ “lấy 20 dòng đầu”.
- Có thể đặt câu hỏi tiếp theo trong cùng cuộc trò chuyện, ví dụ “Chỉ giữ các chuyến đến VVNB” hoặc “Sắp xếp theo giờ cất cánh dự kiến”.

## 5. Nhập câu hỏi bằng giọng nói

Tính năng này hoạt động tốt nhất trên Chrome hoặc Edge.

1. Chọn nút **micro** cạnh nút gửi.
2. Khi trình duyệt hỏi quyền sử dụng micro, chọn **Cho phép**.
3. Khi thấy thông báo **Đang nghe...**, nói câu hỏi bằng tiếng Việt.
4. Chọn lại nút màu đỏ để dừng nếu cần.
5. Kiểm tra văn bản nhận dạng trong ô nhập, sửa các mã sân bay, số hiệu hoặc ngày tháng nếu bị ghi sai.
6. Nhấn **Enter** hoặc chọn nút gửi.

Nếu nút micro bị vô hiệu hóa, hãy chuyển sang Chrome hoặc Edge và kiểm tra quyền micro của trang trong cài đặt trình duyệt.

## 6. Đọc và sử dụng kết quả

### Bảng dữ liệu

Kết quả truy vấn thường được hiển thị dưới dạng bảng. Trong bảng, người dùng có thể:

- Nhập từ khóa vào ô **Search...** để lọc các dòng đang hiển thị.
- Chọn tiêu đề cột để sắp xếp dữ liệu.
- Chọn **📥 Export** để tải bảng về dưới dạng tệp `data.csv`.
- Cuộn ngang nếu bảng có nhiều cột.

Các trường dữ liệu thường gặp:

| Tên hiển thị trong dữ liệu | Ý nghĩa |
|---|---|
| `FLIGHTNBR` | Số hiệu chuyến bay |
| `FLIGHTDATE` | Ngày bay |
| `FROM_AIRP` | Mã sân bay đi |
| `TO_AIRP` | Mã sân bay đến |
| `ETD` | Giờ cất cánh dự kiến |
| `ETA` | Giờ hạ cánh dự kiến |
| `VIA` | Điểm bay qua hoặc điểm trung gian |
| `ATD` | Giờ cất cánh thực tế |
| `ATA` | Giờ hạ cánh thực tế |

### Biểu đồ

Để tạo biểu đồ, hãy yêu cầu rõ loại phân tích và tiêu chí nhóm, ví dụ:

> Vẽ biểu đồ số chuyến bay theo sân bay đến hôm nay, sắp xếp từ cao xuống thấp.

Trợ lí sẽ truy vấn dữ liệu trước, sau đó tạo biểu đồ khi kết quả phù hợp. Nếu chỉ nhận được bảng, hãy hỏi lại và thêm cụm từ **vẽ biểu đồ** hoặc **tạo đồ thị**.

## 7. Gửi phản hồi về kết quả

Khi tính năng phản hồi được bật, sau mỗi truy vấn thành công sẽ xuất hiện hai nút:

- **👍 Đúng:** dùng khi câu truy vấn và kết quả phù hợp với yêu cầu.
- **👎 Không đúng:** dùng khi kết quả sai, thiếu điều kiện hoặc không đúng ý định.

Phản hồi giúp quản trị viên xem xét và cải thiện Trợ lí AI. Phản hồi **👍 Đúng** được đưa vào hàng chờ kiểm tra; hệ thống không tự động dùng kết quả đó để huấn luyện khi chưa được quản trị viên phê duyệt.

## 8. Lệnh trợ giúp

Nhập một trong các lệnh sau vào ô trò chuyện:

| Lệnh | Tác dụng |
|---|---|
| `/help` | Hiển thị hướng dẫn ngắn và các câu hỏi gợi ý. |
| `/h` | Cách viết ngắn của `/help`. |

Người dùng thông thường nên sử dụng các nút **👍 Đúng** và **👎 Không đúng** thay vì tự nhập lệnh phản hồi.

## 9. Phạm vi dữ liệu

Trợ lí hiện làm việc với dữ liệu chuyến bay ATFM trong phạm vi được hệ thống cho phép, chủ yếu gồm:

- Chuyến bay trong ngày và lịch bay dự kiến.
- Chuyến bay đã hoàn thành và thời gian thực tế.
- Số hiệu chuyến bay, ngày bay, sân bay đi/đến, điểm bay qua, giờ dự kiến và giờ thực tế.

Trợ lí không thể trả lời chính xác các câu hỏi cần bảng hoặc trường dữ liệu nằm ngoài phạm vi trên. Khi đó, hãy đổi câu hỏi sang dữ liệu được hỗ trợ hoặc liên hệ quản trị viên.

## 10. Xử lý sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Không có kết quả | Kiểm tra mã sân bay, ngày và điều kiện; sau đó thử nới rộng phạm vi tìm kiếm. |
| Kết quả chưa đúng ý | Viết lại câu hỏi với điều kiện cụ thể hơn và chọn **👎 Không đúng** cho kết quả cũ. |
| Trợ lí hiểu sai ngày | Ghi rõ ngày, tháng, năm, ví dụ `01/01/2025`. |
| Biểu đồ không xuất hiện | Thêm yêu cầu “vẽ biểu đồ” và nêu rõ tiêu chí cần nhóm hoặc so sánh. |
| Micro không hoạt động | Dùng Chrome/Edge, cho phép quyền micro và kiểm tra micro mặc định của máy. |
| Trang báo lỗi kết nối | Kiểm tra mạng, chờ vài giây rồi gửi lại; nếu vẫn lỗi, tải lại trang hoặc liên hệ quản trị viên. |
| Hiển thị “Cần cấu hình” | Liên hệ quản trị viên để kiểm tra kết nối mô hình AI và cơ sở dữ liệu. |

## 11. Lưu ý khi sử dụng

- Không nhập mật khẩu, thông tin đăng nhập hoặc dữ liệu nhạy cảm không cần thiết vào ô trò chuyện.
- Kiểm tra lại số liệu trước khi dùng trong báo cáo hoặc quyết định vận hành.
- Một câu hỏi chỉ nên tập trung vào một mục tiêu phân tích chính. Có thể hỏi tiếp để lọc hoặc trình bày lại kết quả.
- Khi tải lại trang, phiên trò chuyện trên màn hình có thể bắt đầu lại; hãy xuất tệp CSV trước nếu cần lưu kết quả.

