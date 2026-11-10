import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from datetime import datetime
import pytz

st.set_page_config(page_title="雲端鏡頭庫存系統-官方穩定版", layout="centered")
st.title("📱 雲端智能連續掃碼系統")

# 連接 Google Sheets 雲端資料庫
@st.cache_resource
def init_google_sheets():
    client = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    spreadsheet = client.open("inventory")
    inventory_sheet = spreadsheet.get_worksheet(0)
    
    try:
        catalog_sheet = spreadsheet.get_worksheet(1)
        if catalog_sheet is None:
            catalog_sheet = spreadsheet.add_worksheet(title="商品名冊", rows="1000", cols="2")
            catalog_sheet.append_row(["商品編號(SKU)", "商品名稱"])
    except Exception:
        catalog_sheet = spreadsheet.add_worksheet(title="商品名冊", rows="1000", cols="2")
        catalog_sheet.append_row(["商品編號(SKU)", "商品名稱"])
        
    return inventory_sheet, catalog_sheet

try:
    inventory_sheet, catalog_sheet = init_google_sheets()
except Exception as e:
    st.error(f"❌ Google 雲端連線失敗！詳細原因：{str(e)}")
    st.stop()

# --- 初始化 Streamlit 的「暫存盤點籃子」 ---
if "current_barcode" not in st.session_state:
    st.session_state.current_barcode = ""  
if "total_count" not in st.session_state:
    st.session_state.total_count = 0       
if "product_name" not in st.session_state:
    st.session_state.product_name = ""     
if "location_name" not in st.session_state:
    st.session_state.location_name = ""    
if "camera_key" not in st.session_state:
    st.session_state.camera_key = 0

# 1. 條碼影相區域
st.subheader("第一步：連續影相盤點")

# 💥 使用最穩定的官方相機，配合自動遞增的 key 來達成免按 Clear photo 的功能
img_file = st.camera_input(
    "請對準商品條碼拍照（可連續影相累加）", 
    key=f"st_camera_{st.session_state.camera_key}"
)

if img_file is not None:
    file_bytes = np.asarray(bytearray(img_file.read()), dtype=np.uint8)
    opencv_img = cv2.imdecode(file_bytes, 1)
    
    # 這裡已經完美保留了 的解碼修正
    barcodes = decode(opencv_img)
    if barcodes:
        new_scanned_code = barcodes.data.decode('utf-8')
        
        # 判斷是不是同一個 Barcode
        if st.session_state.current_barcode == "":
            st.session_state.current_barcode = new_scanned_code
            st.session_state.total_count = 1
            st.toast(f"🎯 鎖定新條碼：{new_scanned_code}")
            
            # 智能查名冊
            try:
                catalog_data = catalog_sheet.get_all_records()
                found_name = ""
                for item in catalog_data:
                    if str(item.get("商品編號(SKU)")).strip() == str(new_scanned_code).strip():
                        found_name = item.get("商品名稱", "")
                        break
                if found_name:
                    st.session_state.product_name = found_name
            except Exception:
                pass
                
        elif st.session_state.current_barcode == new_scanned_code:
            st.session_state.total_count += 1
            st.toast(f"🔄 偵測到相同條碼！目前累計：{st.session_state.total_count}")
        else:
            st.error(f"⚠️ 警告：條碼不相同！數量未增加。")
        
        # 💥 核心重置魔法：辨識完畢後，立刻讓 key 加 1 並強行 Rerun。
        # 這樣舊照片會被瞬間抹除，鏡頭會一秒重開。因為使用的是官方原生元件，瀏覽器會直接沿用你剛剛選好的「後置主鏡頭」，不會再跳去自拍鏡頭了！
        st.session_state.camera_key += 1
        st.rerun()
    else:
        st.warning("📷 未能辨識條碼，請按下面「Clear photo」重影。")

# 顯示目前的盤點進度
st.info(f"📊 **目前盤點狀態**：\n* 鎖定條碼: `{st.session_state.current_barcode if st.session_state.current_barcode else '尚未開始'}`\n* 累計總數: `{st.session_state.total_count} 件`")

# 清除/重置按鈕
if st.button("清空目前盤點計數 🔄"):
    st.session_state.current_barcode = ""
    st.session_state.total_count = 0
    st.session_state.product_name = ""
    st.session_state.location_name = ""
    st.session_state.camera_key += 1
    st.rerun()

# 2. 商品資訊與位置輸入
st.subheader("第二步：確認資料並同步至雲端")
st.session_state.product_name = st.text_input("商品名稱", value=st.session_state.product_name)
st.session_state.location_name = st.text_input("儲存位置 (例如：A區、3號架、Office)", value=st.session_state.location_name)

# 3. 提交入庫按鈕
if st.button("確認總數並送出入庫 📥", type="primary"):
    if not st.session_state.current_barcode or not st.session_state.product_name or not st.session_state.location_name:
        st.error("❌ 請確保有條碼、品名和位置！")
    elif st.session_state.total_count == 0:
        st.error("❌ 目前累計數量為 0！")
    else:
        with st.spinner("正在檢查雲端並同步庫存..."):
            local_tz = pytz.timezone('Asia/Hong_Kong')
            now_local = datetime.now(local_tz)
            date_str = now_local.strftime("%Y-%m-%d")
            time_str = now_local.strftime("%H:%M")
            
            # 1. 檢查並自動學習新貨品名稱
            try:
                catalog_rows = catalog_sheet.get_all_values()
                is_new_sku = True
                for row in catalog_rows[1:]:
                    if len(row) >= 1 and str(row).strip() == str(st.session_state.current_barcode).strip():
                        is_new_sku = False
                        break
                if is_new_sku:
                    catalog_sheet.append_row([str(st.session_state.current_barcode), st.session_state.product_name])
            except Exception:
                pass
            
            # 2. 庫存智能整合邏輯
            all_rows = inventory_sheet.get_all_values()
            match_row_index = None
            
            for idx, row in enumerate(all_rows[1:], start=2):
                if len(row) >= 4:
                    if str(row).strip() == str(st.session_state.current_barcode).strip() and str(row).strip() == str(st.session_state.location_name).strip():
                        match_row_index = idx
                        break
            
            if match_row_index:
                old_qty = int(all_rows[match_row_index-1])
                new_qty = old_qty + int(st.session_state.total_count)
                
                inventory_sheet.update_cell(match_row_index, 2, st.session_state.product_name)
                inventory_sheet.update_cell(match_row_index, 3, new_qty)                      
                inventory_sheet.update_cell(match_row_index, 5, date_str)                     
                inventory_sheet.update_cell(match_row_index, 6, time_str)                     
                st.success(f"🔄 數量已成功累加更新為 **{new_qty}** 件！")
            else:
                inventory_sheet.append_row([
                    str(st.session_state.current_barcode), 
                    st.session_state.product_name, 
                    int(st.session_state.total_count),
                    st.session_state.location_name,
                    date_str,
                    time_str
                ])
                st.success(f"🎉 成功！新紀錄【{st.session_state.product_name}】已同步至雲端！")
            
            # 上傳成功後自動清空
            st.session_state.current_barcode = ""
            st.session_state.total_count = 0
            st.session_state.product_name = ""
            st.session_state.location_name = ""
            st.session_state.camera_key += 1
            st.rerun()

# 4. 實時顯示雲端庫存
st.subheader("📊 目前雲端最新庫存總覽")
try:
    all_records = inventory_sheet.get_all_records(expected_headers=['商品編號(SKU)', '商品名稱', '數量', '儲存位置', '入庫日期', '入庫時間'])
    if all_records:
        st.dataframe(all_records, use_container_width=True)
except Exception as e:
    st.error(f"❌ 無法載入最新庫存總覽，原因：{str(e)}")
