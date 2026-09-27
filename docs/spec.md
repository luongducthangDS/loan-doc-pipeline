# Spec — Pipeline xử lý hồ sơ vay tiêu dùng (MVP)

> Bản chụp từ doc spec ngày 27/09/2026 để repo tự đủ ngữ cảnh. Bản gốc (có sơ đồ) nằm trong Claude Docs của tác giả.

## 1. Tóm tắt và bối cảnh

MVP tự động hóa khâu tiếp nhận hồ sơ vay tiêu dùng cá nhân qua 3 việc: trích xuất thông tin từ 4 loại giấy tờ, đối chiếu chéo các giấy tờ với nhau, và chỉ chuyển cho người rà soát những bộ có vấn đề. Toàn bộ dữ liệu là synthetic.

**Vấn đề (giả định, xác minh ở M0).** Cán bộ tiếp nhận phải đọc ảnh/scan, nhập tay vào hệ thống, rồi tự so khớp tên, số CCCD và thu nhập giữa các giấy tờ. Việc này tốn thời gian và dễ bỏ sót sai lệch nhỏ, ví dụ thiếu chữ đệm hoặc thu nhập khai cao hơn sao kê. Hiện chưa có số liệu đo thời gian thực tế.

**Câu hỏi dự án phải trả lời.** Ở ngưỡng confidence nào thì pipeline tự xử lý được nhiều bộ hồ sơ nhất mà không để lọt bộ nào có sai lệch? Mọi quyết định thiết kế bên dưới đều nhằm đo được đánh đổi này.

**Ràng buộc.** Một người làm, part-time. Chi phí thấp. Deploy được trên Railway hoặc Render. Không dùng dữ liệu khách hàng thật dưới bất kỳ hình thức nào.

## 2. Mục tiêu, non-goals, tiêu chí thành công

Thước đo thành công là **không để lọt bộ hồ sơ sai lệch nào trên test set**, rồi báo cáo automation rate đạt được ở ngưỡng đó. Accuracy trích xuất cao chưa đủ để gọi là thành công.

**Mục tiêu**

1. Trích xuất field có cấu trúc từ 4 loại giấy tờ (mục 4).
2. Phát hiện sai lệch giữa các giấy tờ bằng rule tất định (mục 7).
3. Route mỗi bộ hồ sơ vào đúng 1 trong 3 nhánh: auto-pass, human review, yêu cầu bổ sung (mục 8).
4. Có eval tái lập được: một lệnh chạy ra báo cáo metric (mục 9).
5. Có demo public chỉ dùng bộ hồ sơ mẫu (mục 10).

**Non-goals của MVP**

- Không chấm điểm tín dụng, không quyết định cho vay. Hệ thống chỉ kiểm tra tính đầy đủ và nhất quán của hồ sơ.
- Không phát hiện giấy tờ giả mạo, không tra CIC, không tích hợp core banking.
- Không fine-tune model.
- Không xử lý dữ liệu thật, kể cả dữ liệu đã ẩn danh.

**Tiêu chí thành công.** Các con số dưới đây là mục tiêu ban đầu, sẽ điều chỉnh sau baseline ở M2.

| Metric | Định nghĩa | Mục tiêu MVP |
|---|---|---|
| Error escape rate | Bộ có sai lệch nhưng bị auto-pass / tổng bộ có sai lệch | 0 ca trên test; báo cáo kèm cận trên 95% |
| Mismatch recall | Sai lệch được rule bắt / tổng sai lệch đã cài | ≥ 95% cho mỗi loại lỗi |
| False review rate | Bộ sạch bị đẩy sang review / tổng bộ sạch | Báo cáo; càng thấp càng tốt |
| Automation rate | Bộ auto-pass / tổng bộ | Là kết quả đầu ra, không đặt trước |
| Field accuracy | Field khớp ground truth sau chuẩn hóa / tổng field | ≥ 95% cho field quan trọng |
| Latency | Thời gian xử lý mỗi bộ, p95 | < 60 giây |
| Chi phí | Chi phí API cho mỗi bộ | Đo và báo cáo |

Field quan trọng gồm: họ tên, số CCCD, ngày sinh, ngày hết hạn CCCD, thu nhập, số tài khoản.

## 3. Người dùng và luồng nghiệp vụ

Hệ thống có 3 vai. Chỉ người rà soát cần giao diện riêng; hai vai còn lại dùng form upload và báo cáo eval.

| Vai | Việc làm với hệ thống | Cần gì |
|---|---|---|
| Cán bộ tiếp nhận | Upload bộ hồ sơ, gắn loại cho từng file | Biết ngay bộ hồ sơ thiếu gì hoặc có vướng gì |
| Người rà soát | Xử lý các bộ trong review queue | Thấy ảnh gốc cạnh field đã trích, lý do bị gắn cờ, sửa được field |
| Engineer (Thang) | Chạy eval, chỉnh prompt và ngưỡng | Trace từng bước, báo cáo metric theo phiên bản |

**User stories**

1. Là cán bộ tiếp nhận, tôi upload 4 giấy tờ và trong vòng 1 phút nhận được một trong 3 kết quả: hợp lệ, cần rà soát (kèm lý do), hoặc thiếu giấy tờ (kèm danh sách cần bổ sung).
2. Là người rà soát, tôi mở một bộ trong queue và thấy ngay rule nào fail, giá trị nào lệch, nằm ở giấy tờ nào. Tôi sửa field nếu model đọc sai rồi chốt quyết định.
3. Là engineer, tôi đổi prompt hoặc ngưỡng rồi chạy make eval để thấy metric thay đổi thế nào so với phiên bản trước.

**Quyết định thiết kế: loại giấy tờ do người upload gắn, không dùng classifier.** Người upload đã biết mình nộp giấy tờ gì, nên đây là thông tin có sẵn và đúng 100%, không tốn công dự đoán. Classifier chuyển sang hạng "nên có".

## 4. Phạm vi giấy tờ và schema trích xuất

MVP hỗ trợ 4 loại giấy tờ bắt buộc. Model chỉ **chép lại** những gì có trên ảnh; mọi giá trị suy ra (như thu nhập trung bình) đều tính bằng code.

| Loại giấy tờ | Field trích xuất | Ghi chú |
|---|---|---|
| CCCD gắn chip, mặt trước + mặt sau | so_cccd, ho_ten, ngay_sinh, gioi_tinh, que_quan, noi_thuong_tru, ngay_cap, ngay_het_han | Chỉ 1 mẫu thẻ. Thẻ căn cước mẫu mới để sau MVP |
| Giấy đề nghị vay vốn | ho_ten, so_cccd, ngay_sinh, so_dien_thoai, dia_chi, ten_cong_ty, thu_nhap_thang, so_tien_vay, thoi_han_thang, muc_dich, so_tk_nhan_luong, ngay_ky | Template do mình tự thiết kế, tên ngân hàng giả |
| Hợp đồng lao động | ho_ten_nld, ten_cong_ty, chuc_danh, loai_hd, ngay_bat_dau, ngay_ket_thuc (có thể null), muc_luong | loai_hd ∈ {xac_dinh_thoi_han, khong_xac_dinh_thoi_han} |
| Sao kê tài khoản 3 tháng | chu_tk, so_tk, ky_tu, ky_den, giao_dich[] gồm {ngay, mo_ta, so_tien, loai} | Có thể nhiều trang; thu nhập trung bình tính từ các giao dịch lương |

**Quy ước chung cho mọi field.** Mỗi field trả về cùng một cấu trúc:

```
{
  "value": "NGUYỄN VĂN AN",
  "raw": "Nguyễn Văn An",
  "confidence": "high",
  "page": 1
}
```

- raw là chuỗi chép nguyên văn từ ảnh. value là giá trị sau chuẩn hóa. Luôn giữ raw để truy vết và debug.
- Model trả null nếu không thấy field trên ảnh, không được đoán.
- Schema định nghĩa bằng Pydantic, dùng làm nguồn duy nhất cho prompt, validate và eval.

**Quy tắc chuẩn hóa (tất định, có unit test)**

| Kiểu | Quy tắc |
|---|---|
| Họ tên | Unicode NFC, viết hoa, gộp khoảng trắng. **Giữ dấu**, vì sai dấu là một sai lệch thật. So khớp hybrid: nếu một bên hoàn toàn không dấu (sao kê in tên không dấu, đơn viết không dấu) thì so sau khi bỏ dấu |
| Ngày | ISO YYYY-MM-DD. Ngày không hợp lệ → null + lỗi validate |
| Tiền | Số nguyên VND, bỏ dấu chấm/phẩy phân tách và chữ "đ", "VNĐ" |
| Số CCCD | Đúng 12 chữ số, sai định dạng → lỗi validate |
| Số tài khoản | Chỉ giữ chữ số |

## 5. Dữ liệu synthetic

Mỗi bộ hồ sơ sinh ra từ **một profile duy nhất**, profile đó là nguồn sự thật. Nhờ vậy các giấy tờ trong bộ nhất quán với nhau, và ground truth có sẵn mà không phải gán nhãn tay.

**Quy trình sinh**

1. **Template.** Crawl mẫu trắng công khai (mẫu đơn vay, HĐLĐ, sao kê) chỉ để tham khảo bố cục. Sau đó dựng lại bằng HTML + Jinja2, dùng tên ngân hàng và logo giả, không chép logo thật. Mỗi loại giấy tờ có 3 layout, trong đó layout thứ 3 chỉ xuất hiện ở test (mục 9), tức là **dev chỉ thấy****2 layout**.
2. **Profile.** Dùng Faker locale vi_VN kèm danh sách tự soạn (họ tên Việt có chữ đệm, tỉnh/thành, tên công ty, mức lương). Seed cố định để chạy lại ra đúng dữ liệu cũ.
3. **Render.** Template + profile → PDF (WeasyPrint hoặc Playwright) → ảnh PNG.
4. **Cài lỗi.** Sửa có chủ đích trên một giấy tờ của bộ và ghi lại vào manifest.
5. **Augmentation.** Tạo 3 mức: clean (render gốc), scan (xoay ±3°, nhiễu, JPEG chất lượng 60), photo (méo phối cảnh, bóng, mờ).
6. **Tập chụp thật.** In 15–20 bộ ra giấy rồi chụp bằng điện thoại. Tập này chỉ dùng để kiểm tra độ bền, không dùng để tinh chỉnh.

**Danh mục lỗi cài**

| Mã | Sai lệch | Cách cài | Rule phải bắt |
|---|---|---|---|
| E1 NAME_MISMATCH | Tên trên đơn khác CCCD | Bỏ chữ đệm, sai 1 dấu, đảo thứ tự | R1 |
| E2 ID_MISMATCH | Số CCCD trên đơn sai | Đổi 1–2 chữ số | R2 |
| E3 DOB_MISMATCH | Ngày sinh trên đơn sai | Lệch ngày hoặc tháng | R3 |
| E4 INCOME_INFLATED | Thu nhập khai cao hơn thực nhận | Khai > lương TB sao kê × 1,2 | R4 |
| E5 ID_EXPIRED | CCCD hết hạn | ngay_het_han < ngay_ky | R5 |
| E6 ACCOUNT_MISMATCH | Tài khoản nhận lương không khớp | Đổi số tài khoản trên đơn | R6 |
| E7 CONTRACT_ENDED | HĐLĐ hết hiệu lực | ngay_ket_thuc < ngay_ky | R7 |
| E8 MISSING_DOC | Thiếu giấy tờ | Bỏ 1 giấy tờ khỏi bộ | R0 |

**Near-miss: biến thể hợp lệ, rule không được gắn cờ.** Ví dụ tên khác nhau chỉ ở chữ hoa/thường hoặc khoảng trắng, thu nhập khai lệch 5% so với sao kê, sao kê có thêm giao dịch ghi có không phải lương. Thiếu nhóm này thì không đo được precision, vì rule gắn cờ mọi thứ vẫn đạt recall 100%.

**Phân bố:** khoảng 50% bộ sạch (trong đó 1/3 có near-miss), 50% có lỗi. Phần lớn bộ lỗi có 1 lỗi, khoảng 10% có 2 lỗi.

**Manifest (****manifest.jsonl****, mỗi dòng một bộ):**

```
{
  "bundle_id": "b_000123",
  "seed": 123,
  "layout_ids": {"cccd": "A", "don_vay": "B", "hdld": "A", "sao_ke": "B"},
  "augment": "photo",
  "docs": [{"doc_id": "d1", "type": "cccd", "files": ["b_000123/cccd_front.png", "b_000123/cccd_back.png"], "fields_gt": {}}],
  "injected_errors": [{"code": "E4", "doc_id": "d2", "field": "thu_nhap_thang"}],
  "near_miss": [],
  "expected_route": "REVIEW"
}
```

## 6. Kiến trúc và data contract

Pipeline là một **workflow tất định gồm 6 bước**. Model chỉ xuất hiện ở bước trích xuất, vì đọc ảnh là việc duy nhất code thường không làm được.

*(Sơ đồ: luồng xử lý · 6 bước, 3 nhánh ra — xem doc gốc)*

Router đưa mỗi bộ hồ sơ vào 1 trong 3 nhánh. Bản sửa của reviewer được lưu lại và trở thành dữ liệu eval.

**Vì sao không dùng agent.** Các bước và thứ tự đã biết trước, không có chỗ nào cần model tự lập kế hoạch. Agent sẽ thêm tính bất định, làm eval khó hơn, và khó giải thích vì sao một hồ sơ bị gắn cờ.

**Vì sao trích xuất từng giấy tờ riêng.** Nếu đưa nhiều giấy tờ vào cùng một prompt, model có thể "sửa" tên trên đơn cho khớp với CCCD và che mất sai lệch thật. Mỗi lần gọi chỉ thấy đúng một giấy tờ.

| Thành phần | Lựa chọn MVP | Lý do | Khi scale |
|---|---|---|---|
| API | FastAPI | Anh đã quen, có OpenAPI sẵn | Giữ nguyên |
| Tiền xử lý | pdf2image + OpenCV | Đủ cho xoay thẳng và resize | Giữ nguyên |
| Trích xuất | VLM qua API. Ứng viên: Qwen2.5-VL-7B-Instruct trên FPT AI Marketplace | Không cần GPU. Chốt ở gate M2 | Self-host on-prem |
| Validate, chuẩn hóa, rule | Pydantic + Python thuần, ngưỡng trong YAML | Unit test được 100%, dễ giải thích | Giữ nguyên |
| Lưu trữ | Filesystem + SQLite | Một file, không cần server | Object storage + Postgres |
| Review UI | Streamlit | Nhanh nhất cho một người làm | Web app có phân quyền |
| Thực thi | Đồng bộ trong request | Đủ cho demo | Background worker + queue |

**Data contract giữa các bước.** Mỗi bước chỉ nhận và trả đúng các object dưới đây, nên có thể test từng bước độc lập.

```
class Field(BaseModel):
    value: str | int | date | None
    raw: str | None
    confidence: Literal["high", "low"]
    page: int | None

class Extraction(BaseModel):
    bundle_id: str
    doc_id: str
    doc_type: DocType
    fields: dict[str, Field]
    model: str
    prompt_version: str
    latency_ms: int

class CheckResult(BaseModel):
    rule_id: str                      # "R4"
    status: Literal["pass", "fail", "unknown"]
    evidence: list[dict]              # [{doc_id, field, value}, ...]
    message: str                      # hiển thị cho reviewer

class Decision(BaseModel):
    bundle_id: str
    route: Literal["AUTO_PASS", "REVIEW", "REQUEST_MORE"]
    reasons: list[str]                # rule_id hoặc "LOW_CONF:<field>"
    rules_version: str
    thresholds_version: str
```

## 7. Rule đối chiếu chéo

Có 9 rule, mỗi rule là một hàm Python thuần, trả về pass, fail hoặc unknown. Kết quả unknown (thiếu field hoặc field confidence thấp) **không bao giờ được coi là pass**.

| Rule | Kiểm tra | Nguồn so khớp | Tolerance (mặc định) | Khi fail |
|---|---|---|---|---|
| R0 | Đủ 4 giấy tờ bắt buộc, ảnh đọc được | Bundle | Không có | REQUEST_MORE |
| R1 | Họ tên trùng nhau | Đơn = CCCD = HĐLĐ = chủ TK sao kê | Khớp sau chuẩn hóa, giữ dấu; bên hoàn toàn không dấu thì so sau khi bỏ dấu (hybrid, mục 4) | REVIEW |
| R2 | Số CCCD trùng nhau | Đơn = CCCD | Khớp tuyệt đối | REVIEW |
| R3 | Ngày sinh trùng nhau | Đơn = CCCD | Khớp tuyệt đối | REVIEW |
| R4 | Thu nhập khai không vượt thực nhận | Đơn ≤ lương TB 3 tháng từ sao kê × (1 + t) | t = 10% | REVIEW |
| R5 | CCCD còn hạn | ngay_het_han ≥ ngay_ky của đơn | Không có | REVIEW |
| R6 | Tài khoản nhận lương trùng | Đơn = số TK trên sao kê | Khớp tuyệt đối | REVIEW |
| R7 | HĐLĐ còn hiệu lực | ngay_ket_thuc là null hoặc ≥ ngay_ky | Không có | REVIEW |
| R8 | Sao kê đủ gần và đủ dài | ky_den cách ngay_ky ≤ 30 ngày, phủ ≥ 3 tháng | 30 ngày | REVIEW |

**Lương trung bình trong R4 tính bằng code, không nhờ model.** Lấy các giao dịch ghi có có mô tả chứa từ khóa lương (cấu hình trong YAML), cộng theo tháng rồi chia trung bình. Không tìm thấy giao dịch lương nào thì R4 trả unknown.

**Fact và assumption.** Các tolerance ở trên là giả định cho demo, không phải chính sách tín dụng của ngân hàng nào. README phải ghi rõ điều này.

**Kiểm thử.** Mỗi rule cần unit test cho 3 trường hợp: pass, fail, và unknown. Ngoài ra có thêm các ca near-miss ở mục 5, là những ca rule không được gắn cờ.

## 8. Routing, confidence và review queue

Router xét các điều kiện theo thứ tự và dừng ở điều kiện đầu tiên thỏa mãn. Chỉ bộ nào qua hết mọi kiểm tra mới được auto-pass.

1. R0 fail, hoặc từ 3 field quan trọng trở lên lỗi định dạng → REQUEST_MORE
2. Có rule fail bất kỳ → REVIEW, lý do là danh sách rule_id
3. Có rule unknown, hoặc có field quan trọng mang confidence low → REVIEW, lý do là LOW_CONF:<field>
4. Còn lại → AUTO_PASS

**Vấn đề của confidence.** VLM không trả về xác suất đã hiệu chỉnh, nên con số confidence do model tự khai không đáng tin. Nếu dùng trực tiếp, ngưỡng sẽ vô nghĩa. Vì vậy MVP dùng confidence nhị phân high / low, suy ra từ các tín hiệu kiểm chứng được:

| Tín hiệu | Cách tính | Chi phí |
|---|---|---|
| Định dạng hợp lệ | Field qua validate kiểu và định dạng (12 chữ số, ngày hợp lệ, tiền > 0) | Miễn phí |
| Tự nhất quán | Trích field quan trọng 2 lần: ảnh gốc và ảnh đã tiền xử lý khác đi, rồi so 2 kết quả | Gấp đôi số lần gọi cho field quan trọng |
| Trả lời rõ ràng | Model không trả null, raw không rỗng | Miễn phí |

Field đạt high khi qua cả 3 tín hiệu. Nếu tín hiệu tự nhất quán quá tốn, có thể bỏ, nhưng chỉ sau khi đo trên dev rằng bỏ nó không làm tăng escape rate.

**Không dùng việc khớp giữa các giấy tờ làm tín hiệu confidence.** Sự khớp đó đã được rule kiểm tra rồi; dùng lại làm confidence sẽ thành lập luận vòng. Confidence chỉ trả lời một câu hỏi: model có đọc đúng giấy tờ này không.

**Hai loại sai và cái giá khác nhau**

- Model đọc sai → rule fail giả → vào REVIEW. Chỉ làm giảm automation rate, không nguy hiểm.
- Model đọc sai theo hướng che mất sai lệch thật, ví dụ thêm dấu cho khớp CCCD → AUTO_PASS sai. Đây là loại **cần đo riêng** và là lý do tồn tại của nhóm lỗi E1.

**Review queue (MVP)**

- Một bảng trong SQLite: bundle_id, route, reasons, trạng thái, người xử lý, thời gian mở và đóng.
- Giao diện Streamlit hiện ảnh gốc cạnh field đã trích. Field bị gắn cờ được tô sáng, kèm evidence từ CheckResult.
- Reviewer sửa field, rồi chọn 1 trong 3 kết luận: hồ sơ hợp lệ, yêu cầu bổ sung, hoặc sai lệch cần làm rõ với khách.
- Ghi lại thời gian xử lý mỗi bộ, để về sau ước lượng thời gian tiết kiệm được so với làm tay.

## 9. Evaluation plan

Eval có 3 tầng: trích xuất, rule, routing end-to-end. Test set được đóng băng và chỉ chạy một lần cho mỗi phiên bản cuối. Mọi việc tinh chỉnh prompt, ngưỡng và phân tích lỗi đều làm trên dev.

**Dataset**

| Tập | Số bộ | Thành phần | Dùng để |
|---|---|---|---|
| dev | 50 | 2 layout/loại, cả 3 mức augmentation | Tinh chỉnh prompt, chọn ngưỡng, phân tích lỗi |
| test | 300 (150 có lỗi) | Cả 3 layout, trong đó layout thứ 3 chưa từng thấy | Báo cáo kết quả, không tinh chỉnh |
| real-capture | 15–20 | Bản in chụp bằng điện thoại | Đo khoảng cách synthetic → ảnh thật |

**Vì sao test cần 150 bộ có lỗi.** Nếu không lọt ca nào trong n bộ có lỗi, cận trên 95% của escape rate vào khoảng 3/n (rule of three). Với 150 bộ, cận trên khoảng 2%. Muốn tuyên bố escape rate ≤ 1% thì cần ít nhất 300 bộ có lỗi. Nếu chưa đủ ngân sách, báo cáo đúng con số cận trên, không làm tròn.

**Metric theo tầng**

1. **Trích xuất.** Field accuracy sau chuẩn hóa, chia theo loại giấy tờ × field × mức augmentation × layout. Tỉ lệ output không qua schema.
2. **Rule.** Recall theo từng mã lỗi E1–E8. Precision tính trên bộ sạch, tách riêng nhóm near-miss.
3. **End-to-end.** Confusion matrix giữa expected_route và route thực tế. Tính escape rate, false review rate, automation rate.
4. **Vận hành.** Latency p50/p95 mỗi bộ, chi phí mỗi bộ, số lần gọi model mỗi bộ.

**Baseline để chứng minh từng thành phần là cần thiết**

- **B0: mọi bộ vào REVIEW.** Automation 0%, escape 0%. Đây là mốc "làm tay" để so sánh.
- **B1: OCR (Tesseract hoặc PaddleOCR tiếng Việt) + regex.** Thuộc nhóm "nên có". Nếu B1 đạt gần VLM thì không cần VLM.
- **B2: VLM**, là phương án chính.

**Đường cong đánh đổi.** Chạy trên dev với nhiều cấu hình router (có hoặc không có tự nhất quán, danh sách field quan trọng khác nhau), vẽ automation rate theo escape rate. Chọn điểm vận hành trên dev, sau đó chạy test một lần duy nhất.

**Cách chạy**

```
make data SEED=42          # sinh dev + test + manifest
make eval SPLIT=dev        # → reports/<run_id>/report.md, metrics.json, errors.csv
```

Mỗi run ghi lại model, prompt_version, rules_version, thresholds_version và git commit. Bảng tổng hợp so sánh run mới với run trước; thay đổi nào làm tăng escape rate thì bị loại, dù automation rate có tăng.

## 10. Yêu cầu phi chức năng

Rủi ro bảo mật lớn nhất của MVP không nằm ở code mà ở **demo public cho phép upload**. Người lạ có thể tải lên CCCD thật, và dữ liệu đó sẽ bị lưu lại và gửi sang API bên thứ ba.

**Bảo mật và dữ liệu cá nhân**

- Demo public chỉ cho chọn bộ hồ sơ mẫu có sẵn, không có nút upload. Upload chỉ bật khi chạy local.
- Repo chỉ chứa dữ liệu synthetic. Thêm bước kiểm tra trong CI để chặn file ảnh nằm ngoài thư mục data/synthetic/.
- API key để trong .env, không commit. Đặt giới hạn chi tiêu phía nhà cung cấp API.
- README ghi rõ: dữ liệu là synthetic, lý do chọn synthetic (Nghị định 13/2023), và ngưỡng rule là giả định.

**Observability.** Mỗi bộ hồ sơ có một file trace JSON, gồm: latency từng bước, model, prompt_version, output thô của model, lỗi validate, CheckResult, Decision. Như vậy mọi quyết định route đều truy ngược được tới đúng lần gọi model đã gây ra nó.

**Tái lập.** Seed cố định, dependency pin trong requirements.txt hoặc uv.lock, prompt đặt trong repo có version, ghi lại tên và phiên bản model trong mỗi run.

**Phân tầng theo mức độ cần thiết**

| Hạng mục | Cần cho MVP | Nên có | Production scale |
|---|---|---|---|
| Lưu trữ | Filesystem + SQLite | Tự xóa file upload sau N ngày | Object storage mã hóa, Postgres, retention policy |
| Thực thi | Đồng bộ | Background task, retry khi API lỗi | Queue, idempotency, dead-letter |
| Model | Một VLM qua API | So 2 model, fallback khi API chết | Self-host on-prem, data residency |
| Phân loại giấy tờ | Người upload tự gắn | VLM classifier | Classifier có confidence + kiểm tra chéo |
| Review UI | Streamlit | Khóa bản ghi khi đang xử lý, phân công | RBAC, SLA, audit đầy đủ |
| Observability | Trace JSON + báo cáo eval | Dashboard metric theo ngày | Tracing, alerting, theo dõi drift |
| Bảo mật | Chỉ synthetic, demo không upload | Che PII trong log | Mã hóa, kiểm soát truy cập, tuân thủ NĐ 13/2023 |

**Latency và chi phí.** Mục tiêu p95 < 60 giây mỗi bộ trên demo. Chi phí đo thực tế ở M2, rồi dùng để quyết định có giữ tín hiệu tự nhất quán hay không.

## 11. Giả định, rủi ro, failure modes, câu hỏi mở

Giả định yếu nhất là **A1: bài toán có thật và đáng giải**. Nếu A1 sai, dự án vẫn chạy được về mặt kỹ thuật nhưng mất phần "so what" khi kể lại trong phỏng vấn.

**Giả định cần xác minh**

| Mã | Giả định | Cách xác minh | Khi nào |
|---|---|---|---|
| A1 | Nhập liệu và đối chiếu tay là điểm nghẽn ở khâu tiếp nhận hồ sơ vay | Hỏi 2–3 cán bộ tín dụng về quy trình và thời gian mỗi bộ; chỉ hỏi về quy trình, không lấy dữ liệu khách hàng | M0 |
| A2 | 4 loại giấy tờ ở mục 4 đại diện cho bộ hồ sơ vay tiêu dùng phổ biến | Cùng buổi hỏi với A1 | M0 |
| A3 | VLM cỡ 7B đọc đủ tốt tiếng Việt có dấu trên ảnh chụp | Spike trên dev | M2 |
| A4 | Dữ liệu synthetic đủ gần thật để kết quả có ý nghĩa | So metric giữa test và tập real-capture | M4 |

**Failure modes**

| Failure | Hậu quả | Phát hiện | Giảm thiểu |
|---|---|---|---|
| Model "sửa" tên hoặc dấu cho giống mẫu quen | Che mất sai lệch → auto-pass sai | Recall của E1, escape rate | Trích từng giấy tờ riêng; prompt yêu cầu chép nguyên văn; giữ raw |
| Model bịa ra field không có trên ảnh | Rule pass hoặc fail sai | Bộ E8, các field cố ý để trống | Schema cho phép null; prompt cấm đoán |
| Output không đúng JSON schema | Pipeline dừng | Tỉ lệ lỗi validate | Retry 1 lần, sau đó route REVIEW |
| Sao kê nhiều trang bị bỏ sót trang | Thu nhập trung bình sai | Số giao dịch so với ground truth | Trích từng trang; kiểm tra số trang đã xử lý |
| Prompt khớp quá sát với layout của chính mình | Kết quả đẹp nhưng ảo | Chênh lệch giữa layout đã thấy và layout thứ 3 | Có layout held-out; báo cáo metric theo layout |
| API chậm hoặc chết | Demo hỏng khi đang trình bày | Latency, tỉ lệ lỗi HTTP | Timeout, retry; demo có sẵn kết quả đã cache |

**Câu hỏi mở**

- Chốt VLM: Qwen2.5-VL-7B qua API hay chạy local? Quyết định ở gate M2, dựa trên accuracy và chi phí.
- Chi phí API cho 300 bộ test, khoảng 1.500–2.500 lần gọi, là bao nhiêu? Chưa có số.
- Có làm baseline OCR B1 hay không? Phụ thuộc thời gian còn lại sau M3.

## 12. Milestones

Dự án chia thành 5 giai đoạn, mỗi giai đoạn kết thúc bằng một gate đo được. Gate M2 là điểm quyết định: nếu VLM không đọc đủ tốt thì xây rule và UI phía sau cũng vô ích.

*(Sơ đồ: roadmap · 5 giai đoạn, 5 gate — xem doc gốc)*

Test set được sinh và đóng băng ngay từ M1, trước khi viết bất kỳ prompt nào, để không thể vô tình tinh chỉnh theo test.

**Nếu thiếu thời gian, cắt theo thứ tự này:** baseline OCR B1 → tập real-capture → tín hiệu tự nhất quán → layout thứ 3. **Không cắt** eval harness, nhóm near-miss và test set đóng băng, vì đây là ba thứ phân biệt dự án này với một OCR demo.
