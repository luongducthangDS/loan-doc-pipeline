# Loan Document Pipeline

Pipeline tự động hóa xử lý hồ sơ vay tiêu dùng: **đọc giấy tờ → trích xuất có cấu trúc → đối chiếu chéo → tự duyệt hồ sơ dễ, đẩy hồ sơ khó cho người**. Mục tiêu đo được: *tỷ lệ hồ sơ chạy thẳng (STP) ở mức lỗi lọt chấp nhận được*.

> Toàn bộ dữ liệu là **tổng hợp** (tên công ty, ngân hàng hư cấu, mọi trang đóng dấu "MẪU"). Không dùng dữ liệu khách hàng thật.

Khác với [`multimodal-idp-vlm`](../multimodal-idp-vlm) (bóc tách **từng** tài liệu, trọng tâm model/inference), repo này là **tầng quy trình**: nhiều giấy tờ của cùng một người, rule đối chiếu, routing, human-in-the-loop và metric nghiệp vụ.

## Trạng thái

| Tuần | Nội dung | Trạng thái |
|---|---|---|
| 1 | Schema, chuẩn hóa, bộ sinh dữ liệu có nhãn | ✅ |
| 2 | Extractor (so sánh OCR+LLM vs VLM trên dev), F1 theo field | ⏳ |
| 3 | Rule đối chiếu chéo, routing, API, UI người duyệt | ⏳ |
| 4 | Đường cong STP vs lỗi lọt, so sánh chi phí, phân tích lỗi | ⏳ |

## Chạy

```bash
pip install -r requirements.txt
pytest -q
python -m datagen.build --n 500 --seed 42          # ~3 phút, ghi vào data/ (đã gitignore)
python -m datagen.build --n 500 --seed 42 --start 300   # chạy tiếp nếu bị ngắt
```

Mỗi hồ sơ: `data/{dev,test}/<app_id>/` gồm `truth.json` (ground truth + nhãn + mức nhiễu) và `cccd.jpg`, `hdld.jpg`, `sao_ke.jpg`, `de_nghi_vay.jpg`.

## Cấu trúc

```
schemas/__init__.py   # Pydantic: 4 loại giấy tờ + Application + mã nhãn
normalize.py          # name_key / parse_money / parse_date
datagen/truth.py      # sinh ground truth, phân tầng theo mã nhãn
datagen/render.py     # vẽ ảnh + nhiễu scan (clean/light/heavy)
datagen/build.py      # CLI sinh bộ dữ liệu, chia dev/test
tests/                # kiểm nhãn khớp dữ liệu, chuẩn hóa, font tiếng Việt
docs/data_card.md     # cách sinh dữ liệu và giới hạn
```

## Quy ước dữ liệu

- Ngày: `date` ISO. Tiền: `int` VND. Tên: giữ nguyên, so khớp qua `name_key` (bỏ dấu, viết hoa).
- Ground truth và output extractor dùng **cùng model** → chấm điểm so thẳng từng field. Confidence/evidence nằm ở wrapper riêng (tuần 2).
