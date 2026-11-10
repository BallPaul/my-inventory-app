import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from datetime import datetime
import pytz

st.set_page_config(page_title="雲端鏡頭庫存系統-自動建檔版", layout="centered")
st.title("📱 雲端智能連續掃碼系統")

# 連接 Google Sheets 雲端資料庫（同時打開庫存表與名冊表）
@st.cache_resource
def init_google_sheets():
    client = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    spreadsheet = client.open("inventory")
    
    # 庫存紀錄工作表 (第一個分頁)
    inventory_sheet = spreadsheet.get_worksheet(0)
    
    # 自動檢查並建立「商品名冊工作表」 (第二個分頁)
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
if "last_processed_barcode" not in st.session_state:
    st.session_state.last_processed_barcode = ""  # 💥 修正版防重複鎖：記錄上一次成功觸發的條碼與狀態

# 1. 條碼影相區域
st.subheader("第一步：連續影相盤點")
img_file = st.camera_input("請對準商品條碼拍照（可連續影相累加）")

if img_file is not None:
    file_bytes = np.asarray(bytearray(img_file.read()), dtype=np.uint8)
    opencv_img = cv2.imdecode(file_bytes, 1)
    
    barcodes = decode(opencv_img)
    if barcodes:
        new_scanned_code = barcodes[0].data.decode('utf-8')
        
        # 💥 智能防重複機制：利用按鈕重置與條碼狀態來鎖定，避免打字重新整理時重複計算
        if st.session_state.last_processed_barcode != img_file.name + "_" + new_scanned_code:
            # 判斷是不是同一個 Barcode
            if st.session_state.current_barcode == "":
                st.session_state.current_barcode = new_scanned_code
                st.session_state.total_count = 1
                st.success(f"🎯 鎖定新條碼：{new_scanned_code}，目前數量：1")
                
                # 智能查名冊：自動去雲端名冊搜尋有沒有紀錄
                with st.spinner("正在幫你從雲端名冊搜尋商品名稱..."):
                    try:
                        catalog_data = catalog_sheet.get_all_records()
                        found_name = ""
                        for item in catalog_data:
                            if str(item.get("商品編號(SKU)")).strip() == str(new_scanned_code).strip():
                                found_name = item.get("商品名稱", "")
                                break
                        if found_name:
                            st.session_state.product_name = found_name
                            st.toast(f"📖 發現舊紀錄！已自動填上品名：{found_name}")
                        else:
                            st.session_state.product_name = "" 
                            st.toast("🆕 偵測到新條碼！稍後入庫時系統會自動記住此品名。")
                    except Exception:
                        st.session_state.product_name = ""
            elif st.session_state.current_barcode == new_scanned_code:
                st.session_state.total_count += 1
                st.success(f"🔄 偵測到相同條碼！目前累計數量：{st.session_state.total_count}")
            else:
                st.error(f"⚠️ 警告：剛剛影的條碼 ({new_scanned_code}) 與目前盤點中的條碼 ({st.session_state.current_barcode}) 不相同！數量未增加。")
            
            # 鎖定目前照片與條碼組合，打字重新整理時不重複計數
            st.session_state.last_processed_barcode = img_file.name + "_" + new_scanned_code
    else:
        st.warning("📷 未能清晰辨識條碼，請調整距離再影一次。")

# 顯示目前的盤點進度
st.info(f"📊 **目前盤點狀態**：\n* 鎖定條碼: `{st.session_state.current_barcode if st.session_state.current_barcode else '尚未開始'}`\n* 累計總數: `{st.session_state.total_count} 件`")

# 清除/重置按鈕
if st.button("清空目前盤點計數 🔄"):
    st.session_state.current_barcode = ""
    st.session_state.total_count = 0
    st.session_state.product_name = ""
    st.session_state.location_name = ""
    st.session_state.last_processed_barcode = ""
    st.rerun()

# 2. 商品資訊與位置輸入
st.subheader("第二步：確認資料並同步至雲端")
st.session_state.product_name = st.text_input("商品名稱", value=st.session_state.product_name)
st.session_state.location_name = st.text_input("儲存位置 (例如：A區、3號架、Office)", value=st.session_state.location_name)

# 3. 提交入庫按鈕 (包含自動建檔整合邏輯)
if st.button("確認總數並送出入庫 📥", type="primary"):
    if not st.session_state.current_barcode or not st.session_state.product_name or not st.session_state.location_name:
        st.error("❌ 請確保有掃描條碼，並填寫商品名稱和儲存位置！")
    elif st.session_state.total_count == 0:
        st.error("❌ 目前累計數量為 0，請先影相盤點！")
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
                    if len(row) >= 1 and str(row[0]).strip() == str(st.session_state.current_barcode).strip():
                        is_new_sku = False
                        break
                
                if is_new_sku:
                    catalog_sheet.append_row([str(st.session_state.current_barcode), st.session_state.product_name])
                    st.toast(f"🧠 系統已自動記住：{st.session_state.current_barcode} ➔ {st.session_state.product_name}")
            except Exception:
                pass
            
            # 2. 進行原本的庫存智能整合邏輯
            all_rows = inventory_sheet.get_all_values()
            match_row_index = None
            
            for idx, row in enumerate(all_rows[1:], start=2):
                if len(row) >= 4:
                    if str(row[0]).strip() == str(st.session_state.current_barcode).strip() and str(row[3]).strip() == str(st.session_state.location_name).strip():
                        match_row_index = idx
                        break
            
            if match_row_index:
                old_qty = int(all_rows[match_row_index-1][2])
                new_qty = old_qty + int(st.session_state.total_count)
                
                inventory_sheet.update_cell(match_row_index, 2, st.session_state.product_name)
                inventory_sheet.update_cell(match_row_index, 3, new_qty)                      
                inventory_sheet.update_cell(match_row_index, 5, date_str)                     
                inventory_sheet.update_cell(match_row_index, 6, time_str)                     
                st.success(f"🔄 庫存已存在！數量已成功由 {old_qty} 件累加更新為 **{new_qty}** 件！")
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
            st.session_state.last_processed_barcode = ""

# 4. 實時顯示雲端庫存
st.subheader("📊 目前雲端最新庫存總覽")
try:
    all_records = inventory_sheet.get_all_records(expected_headers=['商品編號(SKU)', '商品名稱', '數量', '儲存位置', '入庫日期', '入庫時間'])
    if all_records:
        st.dataframe(all_records, use_container_width=True)
except Exception as e:
    st.error(f"❌ 無法載入最新庫存總覽，原因：{str(e)}")
