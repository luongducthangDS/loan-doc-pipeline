"""Danh sách tự soạn để sinh profile. Mọi công ty / ngân hàng đều hư cấu.

Không dùng Faker: locale vi_VN của Faker sinh tên và địa chỉ kém tự nhiên, và thêm một dependency
không cần. Danh sách dưới đây đủ đa dạng cho MVP; mở rộng khi cần.
"""

HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ",
      "Ngô", "Dương", "Lý", "Lương", "Trịnh", "Đinh", "Phan", "Mai", "Tạ", "Quách"]
DEM = {"Nam": ["Văn", "Đức", "Minh", "Quang", "Hữu", "Thành", "Tiến", "Công", "Xuân", "Ngọc",
               "Mạnh", "Trọng", "Việt", "Anh"],
       "Nữ": ["Thị", "Thu", "Ngọc", "Thanh", "Minh", "Phương", "Hồng", "Thùy", "Kim", "Mỹ",
              "Bảo", "Diệu"]}
TEN = {"Nam": ["Nam", "Hùng", "Dũng", "Tuấn", "Long", "Thắng", "Phong", "Khánh", "Đạt", "Sơn",
               "Hiếu", "Quân", "Trung", "Huy", "Lộc", "Thịnh", "Cường", "Vĩnh", "Kiên", "Tùng"],
       "Nữ": ["Lan", "Hương", "Linh", "Trang", "Mai", "Hà", "Thảo", "Yến", "Ngân", "Vy",
              "Huyền", "Nhung", "Loan", "Quyên", "Oanh", "Hạnh", "Duyên", "Trâm", "Ánh", "Ngọc"]}

# (mã tỉnh trong số CCCD, tỉnh/thành, danh sách phường/xã + quận/huyện)
TINH = [
    ("001", "Hà Nội", ["Phường Dịch Vọng, Quận Cầu Giấy", "Phường Bạch Mai, Quận Hai Bà Trưng",
                       "Phường Kim Liên, Quận Đống Đa", "Xã Kim Chung, Huyện Đông Anh"]),
    ("079", "TP. Hồ Chí Minh", ["Phường Bến Nghé, Quận 1", "Phường 12, Quận Tân Bình",
                                "Phường Linh Trung, TP. Thủ Đức", "Phường 7, Quận Gò Vấp"]),
    ("031", "Hải Phòng", ["Phường Máy Tơ, Quận Ngô Quyền", "Phường Lạch Tray, Quận Ngô Quyền"]),
    ("048", "Đà Nẵng", ["Phường Hòa Cường Bắc, Quận Hải Châu", "Phường An Hải Tây, Quận Sơn Trà"]),
    ("036", "Nam Định", ["Phường Vị Xuyên, TP. Nam Định", "Xã Nghĩa Hưng, Huyện Nghĩa Hưng"]),
    ("040", "Nghệ An", ["Phường Hưng Bình, TP. Vinh", "Xã Diễn Châu, Huyện Diễn Châu"]),
    ("038", "Thanh Hóa", ["Phường Điện Biên, TP. Thanh Hóa", "Xã Quảng Tâm, TP. Thanh Hóa"]),
    ("092", "Cần Thơ", ["Phường An Khánh, Quận Ninh Kiều", "Phường Cái Khế, Quận Ninh Kiều"]),
]

CONG_TY = ["CÔNG TY TNHH AN PHÁT", "CÔNG TY CỔ PHẦN MINH LONG", "CÔNG TY TNHH THÀNH ĐẠT",
           "CÔNG TY CỔ PHẦN SAO MAI", "CÔNG TY TNHH PHÚ THỊNH", "CÔNG TY CỔ PHẦN VẠN XUÂN",
           "CÔNG TY TNHH CÔNG NGHỆ HỒNG HÀ", "CÔNG TY CỔ PHẦN THƯƠNG MẠI BẮC NAM",
           "CÔNG TY TNHH DỊCH VỤ LAM SƠN", "CÔNG TY CỔ PHẦN XÂY DỰNG TRƯỜNG AN"]
CHUC_DANH = ["Nhân viên kinh doanh", "Kế toán viên", "Kỹ sư phần mềm", "Nhân viên hành chính",
             "Chuyên viên marketing", "Kỹ thuật viên", "Trưởng nhóm bán hàng", "Giáo viên",
             "Điều dưỡng", "Nhân viên kho vận", "Chuyên viên nhân sự"]
NGAN_HANG = ["NGÂN HÀNG TMCP SAO VIỆT (GIẢ LẬP)", "NGÂN HÀNG TMCP HỒNG LẠC (GIẢ LẬP)",
             "NGÂN HÀNG TMCP ĐÔNG SƠN (GIẢ LẬP)"]
MUC_DICH = ["Mua sắm đồ dùng gia đình", "Sửa chữa nhà ở", "Mua xe máy", "Chi phí học tập",
            "Chi phí y tế", "Tiêu dùng cá nhân", "Tổ chức đám cưới", "Mua sắm thiết bị điện tử"]
CHI_TIEU = ["THANH TOAN QR CUA HANG TIEN LOI", "RUT TIEN ATM", "THANH TOAN HOA DON DIEN",
            "THANH TOAN HOA DON INTERNET", "THANH TOAN QR SIEU THI", "CHUYEN KHOAN TIEN NHA",
            "THANH TOAN THE TIN DUNG", "NAP TIEN DIEN THOAI", "THANH TOAN VE MAY BAY",
            "PHI QUAN LY TAI KHOAN"]
# Mẫu mô tả giao dịch lương; {m}/{y} kỳ lương, {cty} tên công ty không dấu.
LUONG_MAU = ["CT LUONG T{m:02d}/{y} {cty}", "TRA LUONG THANG {m:02d}/{y} - {cty}",
             "{cty} TRA LUONG T{m}", "SALARY {m:02d}/{y} {cty}"]
