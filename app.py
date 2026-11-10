import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from datetime import datetime
import pytz

st.set_page_config(page_title="雲端鏡頭庫存系統-完整對齊版", layout="centered")
st.title("📱 雲端連續掃碼盤點系統")

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
if "size_name" not in st.session_state:
    st.session_state.size_name = "M"       
if "last_detected_barcode" not in st.session_state:
    st.session_state.last_detected_barcode = "" 

# 1. 條碼影相區域
st.subheader("第一步：連續影相盤點")
img_file = st.camera_input("請用後置主鏡頭對準商品條碼拍照")

if img_file is not None:
    file_bytes = np.asarray(bytearray(img_file.read()), dtype=np.uint8)
    opencv_img = cv2.imdecode(file_bytes, 1)
    
    barcodes = decode(opencv_img)
    if barcodes:
        st.session_state.last_detected_barcode = barcodes.data[0].decode('utf-8')
        st.success(f"📷 偵測到條碼：{st.session_state.last_detected_barcode}（請點擊下方按鈕計數）")
    else:
        st.session_state.last_detected_barcode = ""
        st.warning("📷 未能辨識條碼，請調整距離或光線重新拍一張。")

# 手動確認計數按鈕
if st.session_state.last_detected_barcode:
    btn_label = f"計數此條碼 (+1) 📥"
    if st.button(btn_label, use_container_width=True):
        new_code = st.session_state.last_detected_barcode
        
        if st.session_state.current_barcode == "":
            st.session_state.current_barcode = new_code
            st.session_state.total_count = 1
            st.toast(f"🎯 鎖定新條碼：{new_code}")
            
            # 智能查名冊
            try:
                catalog_data = catalog_sheet.get_all_records()
                found_name = ""
                for item in catalog_data:
                    if str(item.get("商品編號(SKU)")).strip() == str(new_code).strip():
                        found_name = item.get("商品名稱", "")
                        break
                if found_name:
                    st.session_state.product_name = found_name
            except Exception:
                pass
        elif st.session_state.current_barcode == new_code:
            st.session_state.total_count += 1
            st.toast(f"🔄 數量已累計：{st.session_state.total_count} 件")
        else:
            st.error(f"⚠️ 警告：此條碼 ({new_code}) 與目前盤點中的條碼 ({st.session_state.current_barcode}) 不相同！")

# 顯示目前的盤點進度
st.info(f"📊 **目盤點狀態**：\n* 鎖定條碼: `{st.session_state.current_barcode if st.session_state.current_barcode else '尚未開始'}`\n* 累計總數: `{st.session_state.total_count} 件`")

# 清除/重置按鈕
if st.button("清空目前盤點計數 🔄"):
    st.session_state.current_barcode = ""
    st.session_state.total_count = 0
    st.session_state.product_name = ""
    st.session_state.location_name = ""
    st.session_state.size_name = "M"
    st.session_state.last_detected_barcode = ""
    st.rerun()

# 2. 商品資訊、尺寸與位置輸入
st.subheader("第二步：確認資料並同步至雲端")
st.session_state.product_name = st.text_input("商品名稱", value=st.session_state.product_name)

# 尺寸快速下拉選單
size_options = ["SS", "S", "M", "L", "XL", "XXL", "手動輸入其他尺寸..."]
default_idx = size_options.index(st.session_state.size_name) if st.session_state.size_name in size_options else 2
selected_size = st.selectbox("商品尺寸 (Size)", options=size_options, index=default_idx)

if selected_size == "手動輸入其他尺寸...":
    st.session_state.size_name = st.text_input("請輸入自訂尺寸 / 規格", value="")
else:
    st.session_state.size_name = selected_size

st.session_state.location_name = st.text_input("儲存位置 (例如：A區、3號架、Office)", value=st.session_state.location_name)

# 3. 提交入庫按鈕 (完全對齊你的 7 欄 Excel)
if st.button("確認總數並送出入庫 📥", type="primary"):
    if not st.session_state.current_barcode or not st.session_state.product_name or not st.session_state.location_name or not st.session_state.size_name:
        st.error("❌ 請確保有條碼、品名、尺寸和儲存位置！")
    elif st.session_state.total_count == 0:
        st.error("❌ 目前累計數量為 0！")
    else:
        with st.spinner("正在將數據及時間戳同步至 Google 雲端..."):
            # 🕒 獲取精準香港當地時間
            local_tz = pytz.timezone('Asia/Hong_Kong')
            now_local = datetime.now(local_tz)
            date_str = now_local.strftime("%Y-%m-%d")
            time_str = now_local.strftime("%H:%M")
            
            # 1. 檢查並自動學習新貨品名稱
            try:
                catalog_rows = catalog_sheet.get_all_values()
                is_new_sku = True
                for row in catalog_rows[1:]:
                    if len(row) >= 1 and str(row[0]).strip() == str(st.session_state.current_barcode).strip():
                        is_new_sku = False
                        break
                if is_new_sku:
                    catalog_sheet.append_row([str(st.session_state.current_barcode), st.session_state.product_name])
            except Exception:
                pass
            
            # 2. 智能整合查重（比對 SKU + 尺寸 + 儲存位置）
            all_rows = inventory_sheet.get_all_values()
            match_row_index = None
            
            for idx, row in enumerate(all_rows[1:], start=2):
                if len(row) >= 5:
                    sheet_sku = str(row[0]).strip()       # A 欄 SKU
                    sheet_size = str(row[3]).strip()      # D 欄 尺寸
                    sheet_location = str(row[4]).strip()  # E 欄 位置
                    
                    current_sku = str(st.session_state.current_barcode).strip()
                    current_size = str(st.session_state.size_name).strip()
                    current_location = str(st.session_state.location_name).strip()
                    
                    if sheet_sku == current_sku and sheet_size == current_size and sheet_location == current_location:
                        match_row_index = idx
                        break
            
            if match_row_index:
                try:
                    old_qty = int(all_rows[match_row_index-1][2]) # C 欄舊數量
                except (ValueError, IndexError):
                    old_qty = 0
                    
                new_qty = old_qty + int(st.session_state.total_count)
                
                # 智能更新對應格
                inventory_sheet.update_cell(match_row_index, 2, st.session_state.product_name) # B: 品名
                inventory_sheet.update_cell(match_row_index, 3, new_qty)                      # C: 數量
                inventory_sheet.update_cell(match_row_index, 6, date_str)                     # F: 日期
                inventory_sheet.update_cell(match_row_index, 7, time_str)                     # G: 時間
                st.success(f"🔄 雲端紀錄已存在！【{st.session_state.product_name}】數量已更新為 **{new_qty}** 件！")
            else:
                # 完全符合你的 7 欄 Excel 順序進行全新寫入
                inventory_sheet.append_row([
                    str(st.session_state.current_barcode),  # A: 商品編號(SKU)
                    str(st.session_state.product_name),     # B: 商品名稱
                    int(st.session_state.total_count),      # C: 數量
                    str(st.session_state.size_name),        # D: 尺寸
                    str(st.session_state.location_name),    # E: 儲存位置
                    date_str,                               # F: 入庫日期
                    time_str                                # G: 入庫時間
                ])
                st.success(f"🎉 成功！數據連同日期、時間已完美同步至雲端表格！")
            
            # 上傳成功後自動清空
            st.session_state.current_barcode = ""
            st.session_state.total_count = 0
            st.session_state.product_name = ""
            st.session_state.location_name = ""
            st.session_state.size_name = "M"
            st.session_state.last_detected_barcode = ""
            st.rerun()

# 4. 實時顯示雲端庫存
st.subheader("📊 目前雲端最新庫存總覽")
try:
    all_records = inventory_sheet.get_all_records(expected_headers=['商品編號(SKU)', '商品名稱', '數量', '尺寸', '儲存位置', '入庫日期', '入庫時間'])
    if all_records:
        st.dataframe(all_records, use_container_width=True)
except Exception as e:
    st.error(f"❌ 無法載入最新庫存總覽，原因：{str(e)}")
