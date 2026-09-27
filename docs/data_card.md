# Data card — bộ hồ sơ vay tổng hợp

## Cách sinh
1. `datagen/truth.py` sinh ground truth trước (seed cố định), sau đó `render.py` vẽ ảnh từ truth → nhãn đúng 100%.
2. **Phân tầng**: 60% hồ sơ sạch; 40% còn lại chia **đều** cho 10 mã (6 lỗi + 4 biến thể vô hại). Với `--n 500`: 20 hồ sơ/mã.
3. Chia tập cố định theo index: `i % 5 ∈ {0,1}` → test (40%), còn lại → dev. **Không nhìn test khi tune prompt/ngưỡng.**

## Nhãn

| Mã | Loại | Ý nghĩa | Hệ thống phải |
|---|---|---|---|
| `name_mismatch` | lỗi | Tên trên HĐLĐ là người khác | gắn cờ |
| `id_mismatch` | lỗi | Số CCCD trên đơn ≠ CCCD | gắn cờ |
| `income_inflated` | lỗi | Thu nhập khai ≥ 1,3× lương TB trên sao kê | gắn cờ |
| `contract_expired` | lỗi | HĐLĐ hết hạn trước ngày nộp | gắn cờ |
| `cccd_expired` | lỗi | CCCD hết hạn trước ngày nộp | gắn cờ |
| `missing_doc` | lỗi | Thiếu CCCD / HĐLĐ / sao kê | gắn cờ |
| `name_no_diacritics` | vô hại | Đơn ghi tên không dấu | **không** gắn cờ |
| `near_threshold_income` | vô hại | Khai cao hơn 8–12% (dưới ngưỡng 15%) | **không** gắn cờ |
| `cccd_expires_soon` | vô hại | CCCD còn hạn < 30 ngày | **không** gắn cờ |
| `salary_paid_late` | vô hại | Lương tháng cuối về sau kỳ sao kê → chỉ 2 khoản lương | **không** gắn cờ |

Định nghĩa thu nhập thực nhận: trung bình các giao dịch `CT LUONG ...` **có trong kỳ** (không chia cứng cho 3). Lương net = gross × (1 − 10,5% bảo hiểm), bỏ qua thuế TNCN.

## Đa dạng hóa có chủ đích
- Định dạng tiền: `15.000.000 đồng`, `15.000.000 VNĐ`, `15.000.000đ`, `15,5 triệu`; sao kê dùng dấu phẩy `15,000,000`.
- Định dạng ngày: `dd/mm/yyyy`, `dd-mm-yyyy`, `ngày dd tháng mm năm yyyy`.
- Nhiễu scan mỗi trang: clean / light (xoay ±1°, mờ nhẹ) / heavy (xoay ±3°, mờ, giảm tương phản, nhiễu hạt, JPEG q70).

## Giới hạn (phải nêu khi báo cáo kết quả)
- Layout đơn giản, một cột, font máy in → **dễ hơn giấy tờ thật** (ảnh chụp điện thoại, con dấu, chữ viết tay, bảng nhiều trang). Kết quả trên bộ này là **cận trên**.
- Mỗi hồ sơ lỗi chỉ có 1 mã; thực tế có thể nhiều lỗi cùng lúc.
- Tập test ~8 hồ sơ/mã → recall theo từng mã có khoảng tin cậy rộng; báo cáo kèm số mẫu.
- Phân phối (tỷ lệ lỗi, mức lương, loại HĐLĐ) là giả định, không phản ánh danh mục thật của ngân hàng nào.
