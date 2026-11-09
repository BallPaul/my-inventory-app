import streamlit as st
import gspread
import cv2
import numpy as np
from pyzbar.pyzbar import decode

st.set_page_config(page_title="雲端鏡頭庫存系統", layout="centered")
st.title("📱 雲端鏡頭庫存系統 (Google Sheets)")

# 使用 Streamlit 官方最穩定的免檔案連線方式
@st.cache_resource
def init_google_sheets():
    # 直接從 Streamlit 的秘密設定 secrets.toml 中讀取憑證
    client = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    sheet = client.open("inventory").sheet1
    return sheet

try:
    sheet = init_google_sheets()
except Exception as e:
    st.error(f"❌ Google 雲端連線失敗！詳細原因：{str(e)}")
    st.stop()

# 1. 條碼掃描區域
st.subheader("第一步：掃描條碼")
img_file = st.camera_input("請用手機/電腦相機對準條碼拍照")

scanned_code = ""
if img_file is not None:
    file_bytes = np.asarray(bytearray(img_file.read()), dtype=np.uint8)
    opencv_img = cv2.imdecode(file_bytes, 1)
    
    barcodes = decode(opencv_img)
    if barcodes:
        scanned_code = barcodes.data.decode('utf-8')
        st.success(f"✨ 成功辨識條碼：{scanned_code}")
    else:
        st.warning("📷 已拍照，但未能辨識到清晰的條碼，請調整距離或光線再試一次。")

sku_input = st.text_input("商品編號 (SKU)", value=scanned_code)

# 2. 商品詳細資料輸入
st.subheader("第二步：輸入商品資訊")
name_input = st.text_input("商品名稱")
qty_input = st.number_input("入庫數量", min_value=1, value=1, step=1)

# 3. 提交入庫按鈕
if st.button("確認入庫 📥", type="primary"):
    if not sku_input or not name_input:
        st.error("❌ 請確保商品編號和名稱皆已填寫！")
    else:
        with st.spinner("正在同步寫入 Google 雲端..."):
            sheet.append_row([str(sku_input), name_input, int(qty_input)])
            st.success(f"🎉 成功！【{name_input}】共 {qty_input} 件已同步至 Google Drive 表格！")

# 4. 實時顯示雲端庫存
st.subheader("📊 目前雲端最新庫存總覽")
try:
    all_records = sheet.get_all_records()
    if all_records:
        st.dataframe(all_records, use_container_width=True)
    else:
        st.info("目前雲端表格內尚無庫存數據。")
except Exception as e:
    st.warning("暫時無法即時載入總覽表格（但不影響入庫功能）。")
