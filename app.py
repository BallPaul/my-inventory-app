import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from datetime import datetime
import pytz

st.set_page_config(page_title="雲端鏡頭庫存系統-倉位盤點版", layout="centered")
st.title("📱 雲端連續掃碼盤點系統")

# 使用 Streamlit 官方最穩定的免檔案連線方式
@st.cache_resource
def init_google_sheets():
    client = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    sheet = client.open("inventory").sheet1
    return sheet

try:
    sheet = init_google_sheets()
except Exception as e:
    st.error(f"❌ Google 雲端連線失敗！詳細原因：{str(e)}")
    st.stop()

# --- 初始化 Streamlit 的「暫存盤點籃子」 ---
if "current_barcode" not in st.session_state:
    st.session_state.current_barcode = ""  # 目前鎖定的條碼
if "total_count" not in st.session_state:
    st.session_state.total_count = 0       # 累計數量
if "product_name" not in st.session_state:
    st.session_state.product_name = ""     # 商品名稱
if "location_name" not in st.session_state:
    st.session_state.location_name = ""    # 儲存位置
if "last_image_size" not in st.session_state:
    st.session_state.last_image_size = 0   # 💥 照片安全鎖：記錄上一張照片的檔案大小 (Byte)

# 1. 條碼影相區域
st.subheader("第一步：連續影相盤點")
img_file = st.camera_input("請對準商品條碼拍照（可連續影相累加）")

if img_file is not None:
    # 💥 獲取這張照片的二進位數據並計算大小
    img_bytes = img_file.getvalue()
    current_size = len(img_bytes)
    
    # 💥 檢查這張照片的大小是不是跟剛才那張一模一樣
    if current_size != st.session_state.last_image_size:
        file_bytes = np.asarray(bytearray(img_bytes), dtype=np.uint8)
        opencv_img = cv2.imdecode(file_bytes, 1)
        
        barcodes = decode(opencv_img)
        if barcodes:
            new_scanned_code = barcodes[0].data.decode('utf-8')
            
            # 判斷是不是同一個 Barcode
            if st.session_state.current_barcode == "":
                st.session_state.current_barcode = new_scanned_code
                st.session_state.total_count = 1
                st.success(f"🎯 鎖定新條碼：{new_scanned_code}，目前數量：1")
            elif st.session_state.current_barcode == new_scanned_code:
                st.session_state.total_count += 1
                st.success(f"🔄 偵測到相同條碼！目前累計數量：{st.session_state.total_count}")
            else:
                st.error(f"⚠️ 警告：剛剛影的條碼 ({new_scanned_code}) 與目前盤點中的條碼 ({st.session_state.current_barcode}) 不相同！數量未增加。")
        else:
            st.warning("📷 未能清晰辨識條碼，請調整距離或光線再影一次。")
        
        # 💥 辨識完畢後，立刻把這張照片的大小鎖定，防止打字刷新時重複觸發
        st.session_state.last_image_size = current_size

# 顯示目前的盤點進度
st.info(f"📊 **目目前盤點狀態**：\n* 鎖定條碼: `{st.session_state.current_barcode if st.session_state.current_barcode else '尚未開始'}`\n* 累計總數: `{st.session_state.total_count} 件`")

# 清除/重置按鈕
if st.button("清空目前盤點計數 🔄"):
    st.session_state.current_barcode = ""
    st.session_state.total_count = 0
    st.session_state.product_name = ""
    st.session_state.location_name = ""
    st.session_state.last_image_size = 0
    st.rerun()

# 2. 商品資訊與位置輸入
st.subheader("第二步：確認資料並同步至雲端")
st.session_state.product_name = st.text_input("商品名稱", value=st.session_state.product_name)
st.session_state.location_name = st.text_input("儲存位置 (例如：A區、3號架、Office)", value=st.session_state.location_name)

# 3. 提交入庫按鈕
if st.button("確認總數並送出入庫 📥", type="primary"):
    if not st.session_state.current_barcode or not st.session_state.product_name or not st.session_state.location_name:
        st.error("❌ 請確保有掃描條碼，並填寫商品名稱和儲存位置！")
    elif st.session_state.total_count == 0:
        st.error("❌ 目前累計數量為 0，請先影相盤點！")
    else:
        with st.spinner("正在將總數與位置同步至 Google 雲端..."):
            local_tz = pytz.timezone('Asia/Hong_Kong')
            now_local = datetime.now(local_tz)
            
            date_str = now_local.strftime("%Y-%m-%d")
            time_str = now_local.strftime("%H:%M")
            
            sheet.append_row([
                str(st.session_state.current_barcode), 
                st.session_state.product_name, 
                int(st.session_state.total_count),
                st.session_state.location_name,
                date_str,
                time_str
            ])
            st.success(f"🎉 成功！【{st.session_state.product_name}】共 {st.session_state.total_count} 件已成功記錄並同步雲端！")
            
            # 上傳成功後自動清空
            st.session_state.current_barcode = ""
            st.session_state.total_count = 0
            st.session_state.product_name = ""
            st.session_state.location_name = ""
            st.session_state.last_image_size = 0

# 4. 實時顯示雲端庫存
st.subheader("📊 目前雲端最新庫存總覽")
try:
    all_records = sheet.get_all_records(expected_headers=['商品編號(SKU)', '商品名稱', '數量', '儲存位置', '入庫日期', '入庫時間'])
    if all_records:
        st.dataframe(all_records, use_container_width=True)
except Exception as e:
    st.error(f"❌ 無法載入最新庫存總覽，原因：{str(e)}")
