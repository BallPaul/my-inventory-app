import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from datetime import datetime
import pytz

st.set_page_config(page_title="雲端鏡頭庫存系統-連續盤點時間版", layout="centered")
st.title("📱 雲端連續掃碼盤點系統 (含時間戳)")

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

# 1. 條碼影相區域
st.subheader("第一步：連續影相盤點")
img_file = st.camera_input("請對準商品條碼拍照（可連續影相累加）")

if img_file is not None:
    file_bytes = np.asarray(bytearray(img_file.read()), dtype=np.uint8)
    opencv_img = cv2.imdecode(file_bytes, 1)
    
    barcodes = decode(opencv_img)
    if barcodes:
        new_scanned_code = barcodes.data.decode('utf-8')
        
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
        st.warning("📷 未能清晰辨識條碼，請調整距離再影一次。")

# 顯示目前的盤點進度
st.info(f"📊 **目前盤點狀態**：\n* 鎖定條碼: `{st.session_state.current_barcode if st.session_state.current_barcode else '尚未開始'}`\n* 累計總數: `{st.session_state.total_count} 件`")

# 清除/重置按鈕
if st.button("清空目前盤點計數 🔄"):
    st.session_state.current_barcode = ""
    st.session_state.total_count = 0
    st.session_state.product_name = ""
    st.experimental_rerun()

# 2. 商品名稱輸入與上傳
st.subheader("第二步：確認資料並同步至雲端")
st.session_state.product_name = st.text_input("商品名稱", value=st.session_state.product_name)

# 3. 提交入庫按鈕
if st.button("確認總數並送出入庫 📥", type="primary"):
    if not st.session_state.current_barcode or not st.session_state.product_name:
        st.error("❌ 請確保有掃描條碼並填寫商品名稱！")
    elif st.session_state.total_count == 0:
        st.error("❌ 目前累計數量為 0，請先影相盤點！")
    else:
        with st.spinner("正在將總數同步至 Google 雲端..."):
            # 🕒 獲取香港/台北時間（避免雲端伺服器用錯外國時間）
            local_tz = pytz.timezone('Asia/Hong_Kong')
            now_local = datetime.now(local_tz)
            
            # 格式化日期和時間（例如：2026-11-09 22:30）
            date_str = now_local.strftime("%Y-%m-%d")
            time_str = now_local.strftime("%H:%M")
            
            # 將新資料追加到 Google Sheets（最後加上了日期和時間欄位）
            sheet.append_row([
                str(st.session_state.current_barcode), 
                st.session_state.product_name, 
                int(st.session_state.total_count),
                date_str,
                time_str
            ])
            st.success(f"🎉 成功！【{st.session_state.product_name}】總共 {st.session_state.total_count} 件已整筆寫入雲端！")
            
            # 上傳成功後自動清空
            st.session_state.current_barcode = ""
            st.session_state.total_count = 0
            st.session_state.product_name = ""

# 4. 實時顯示雲端庫存
st.subheader("📊 目前雲端最新庫存總覽")
try:
    all_records = sheet.get_all_records()
    if all_records:
        st.dataframe(all_records, use_container_width=True)
except Exception as e:
    pass
