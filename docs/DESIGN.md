# Design

## Review UI (Streamlit, `app.py` + `.streamlit/config.toml`)
- Phong cách back-office ngân hàng: navy + nền xám lạnh; tránh đỏ mặc định vì trông như báo lỗi.
- Theme: `primaryColor #1B3A66`, `backgroundColor #EEF1F5`, `secondaryBackgroundColor #F6F8FA`, `textColor #16202E`, `borderColor #C3CCD8`, `baseRadius 6px`; toolbar tối giản.
- Font: Be Vietnam Pro (chữ), IBM Plex Mono (mã, số liệu); số dùng `tabular-nums`.
- Thanh trên navy `#0B1F3A` với logo viền vàng `#C9A45C`; link `#1B4F9C` (hover `#0E3470`); dải ghi chú nền `#FFF6E3`, viền `#EFD7A6`, chữ `#5E3B00`; breadcrumb `#5A6678`.
- Icon bằng CSS mask (`.ico`). `st.set_page_config(page_title="Thẩm định hồ sơ vay", page_icon="📄", layout="wide")`.
- Mỗi trang giấy tờ synthetic in dòng "MẪU – DỮ LIỆU TỔNG HỢP".
- 2 trang trên thanh nav (mục đang mở gạch chân vàng): Hàng đợi (`?`, mặc định) và Tổng quan pipeline (`?page=overview`): hero gradient navy, 4 KPI kết quả đo, 4 bước pipeline, lưới rule R0–R8, bảng so sánh biến thể. Số trên trang tổng quan chép tay từ README/`reports/comparison.md` (`RESULTS` trong `app.py`).
- Responsive: ≤1100px lưới 2 cột, bảng hàng đợi cuộn ngang (min 1040px); ≤640px 1 cột, ẩn nhãn env/tên brand, thanh kết luận hết sticky. Media query phải có tiền tố `.stApp` vì Streamlit có thể chèn rule gốc sau.

## Báo cáo eval
`reports/<run_id>/report.md` + `metrics.json` + `errors.csv` + trace JSON từng bộ; `reports/runs.csv` gom mọi lần chạy. Escape rate luôn kèm cận trên 95 %; chế độ agent có thêm token, chi phí, latency.
