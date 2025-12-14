# app.py
import streamlit as st
import requests
import pandas as pd
from ftplib import FTP
from io import StringIO
import re
import time

# --- 定数設定 ---
# APIのエンドポイント
API_URL = "https://www.showroom-live.com/api/event/room_list"
# FTPアップロード先のファイル名とパス (ユーザー様修正済みパス)
FTP_FILE_PATH = "/mksoul-pro.com/showroom/file/event_liver_list.csv"

# --- 関数: APIから全ページデータを取得 ---
@st.cache_data(show_spinner="イベント参加ルーム情報を取得中...")
def fetch_all_room_data(event_id):
    """
    指定されたイベントIDの全ページからルーム情報を取得し、
    ルームIDとイベントIDのリストを返します。
    """
    st.write(f"イベントID: **{event_id}** の情報を取得します。")
    all_rooms = []
    page = 1
    
    # ページング処理を無限ループで行い、データがなくなるまで続ける
    while True:
        try:
            # API URLを構築
            url = f"{API_URL}?event_id={event_id}&p={page}"
            
            # APIコール
            response = requests.get(url, timeout=10)
            response.raise_for_status() # HTTPエラーが発生した場合に例外を発生させる
            data = response.json()

            # ルームリストを抽出
            room_list = data.get("list", [])
            
            if not room_list:
                # リストが空であれば、最終ページに到達したと判断してループを終了
                st.info(f"ページ {page}: ルームが見つかりませんでした。全 {page-1} ページを処理しました。")
                break

            # データを処理して、ルームIDとイベントIDのペアを抽出
            for room_data in room_list:
                # room_idはトップレベルまたはevent_entryネスト内にあります。
                # どちらも同じ情報であるため、トップレベルのものを採用します。
                room_id = room_data.get("room_id")
                # event_entryネスト内のevent_idを取得
                entry_data = room_data.get("event_entry", {})
                current_event_id = entry_data.get("event_id")

                if room_id and current_event_id:
                    # room_idは文字列型と数値型が混在している可能性があるため、文字列に統一
                    all_rooms.append({
                        "room_id": str(room_id),
                        "event_id": str(current_event_id)
                    })
            
            # APIのレスポンスから次のページ番号を取得
            next_page = data.get("next_page")
            st.text(f"ページ {page} 処理完了。次ページ: {next_page}")

            if next_page is None or next_page == page:
                # next_pageが存在しないか、現在のページと同じ場合はループ終了
                break

            page = next_page
            # サーバー負荷軽減のため、ページ間に短い待機時間を設ける
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            st.error(f"APIリクエストエラー (ページ {page}): {e}")
            break
        except Exception as e:
            st.error(f"予期せぬエラーが発生しました (ページ {page}): {e}")
            break

    return all_rooms

# --- 関数: FTPからファイルをダウンロード ---
def download_ftp_file(ftp, remote_path):
    """FTPサーバーから既存のCSVファイルをダウンロードし、Pandas DataFrameとして返します。"""
    st.info(f"FTPサーバーから既存ファイル **{remote_path}** のダウンロードを試みます。")
    try:
        # ダウンロードしたデータを保持するためのStringIOバッファ
        r = StringIO()
        # ファイルを取得してバッファに書き込む
        ftp.retrlines(f'RETR {remote_path}', lambda x: r.write(x + '\n'))
        r.seek(0)
        
        # バッファからDataFrameを読み込む
        # ヘッダーがないファイルも考慮し、namesを指定
        df = pd.read_csv(r, header=None, names=['room_id', 'event_id'], dtype=str)
        st.success("既存ファイルをダウンロードしました。")
        return df
    
    except Exception as e:
        # ファイルが存在しない場合や、読み込みエラーの場合は空のDataFrameを返す
        st.warning(f"既存ファイルのダウンロードまたは読み込みに失敗しました。新規ファイルとして処理します。エラー: {e}")
        return pd.DataFrame(columns=['room_id', 'event_id'], dtype=str)

# --- 関数: DataFrameをFTPにアップロード ---
def upload_ftp_file(ftp, df, remote_path):
    """DataFrameをCSV形式でFTPサーバーにアップロードします。"""
    st.info(f"処理結果をFTPサーバーの **{remote_path}** にアップロードしています...")
    try:
        # DataFrameをCSV文字列に変換（ヘッダーなし、インデックスなし）
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, header=False, encoding='utf-8')
        csv_buffer.seek(0)
        
        # FTPにアップロード (STORLINESを使用 - テキストファイル用)
        # StringIOは文字列を扱うため、storlinesに修正します
        ftp.storlines(f'STOR {remote_path}', csv_buffer) # 💡 修正箇所
        st.success("✅ CSVファイルが正常にFTPサーバーにアップロードされました。")
        st.caption(f"アップロード先: {ftp.host}:{remote_path}")

    except Exception as e:
        st.error(f"FTPアップロード中にエラーが発生しました: {e}")

# --- メイン Streamlit アプリケーション ---
def main():
    # ... (main関数は変更なし) ...
    st.title("SHOWROOM イベント参加ルームID 抽出・FTPアップロード")
    st.markdown("---")
    
    # --- 1. イベントID入力 ---
    event_ids_input = st.text_area(
        "📝 イベントIDを入力してください (複数可。改行またはカンマ区切り):",
        help="例: 40883, 40884\nまたは\n40883\n40884"
    )
    
    # 複数のイベントIDを解析
    event_ids = []
    if event_ids_input:
        # 改行またはカンマで分割し、不要な空白を除去
        raw_ids = re.split(r'[\n,]+', event_ids_input.strip())
        # 空でない、数字のみの文字列を抽出
        event_ids = [eid.strip() for eid in raw_ids if eid.strip().isdigit()]

    if not event_ids:
        st.warning("イベントIDを入力してください。")
        return

    st.info(f"処理対象のイベントID: **{', '.join(event_ids)}**")
    st.markdown("---")

    # --- 2. 実行ボタン ---
    if st.button("🚀 実行: ルームID取得 & FTPアップロード"):
        
        # 全イベントのデータ取得
        new_data_list = []
        with st.spinner("APIからデータを取得中..."):
            for event_id in event_ids:
                rooms = fetch_all_room_data(event_id)
                new_data_list.extend(rooms)
        
        if not new_data_list:
            st.error("入力された全てのイベントIDについて、ルーム情報を取得できませんでした。処理を中断します。")
            return
            
        # 取得データをDataFrameに変換
        new_df = pd.DataFrame(new_data_list, dtype=str)
        # 列の順番を要件通りに [room_id, event_id] に設定
        new_df = new_df[['room_id', 'event_id']]
        st.subheader("✅ 取得した新規データ")
        st.dataframe(new_df)
        st.success(f"全イベントから合計 **{len(new_df)}** 件のルームIDを取得しました。")
        
        # --- 3. FTP接続とデータ処理 ---
        st.markdown("---")
        st.header("🔄 データ結合・重複排除・FTPアップロード")
        
        try:
            # secretsからFTP情報を取得
            ftp_host = st.secrets["ftp"]["host"]
            ftp_user = st.secrets["ftp"]["user"]
            ftp_pass = st.secrets["ftp"]["password"]
            
            # FTP接続
            with FTP(ftp_host) as ftp:
                ftp.login(user=ftp_user, passwd=ftp_pass)
                # パッシブモードを設定 (一部のホスティング環境で必要)
                ftp.set_pasv(True) 
                
                # 既存ファイルのダウンロード
                existing_df = download_ftp_file(ftp, FTP_FILE_PATH)
                
                # 取得した新しいデータと既存データを結合
                # room_idとevent_idの列があることを確認
                if not existing_df.empty:
                    # 結合前に念のため型を文字列に統一
                    existing_df = existing_df.astype(str)
                    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                else:
                    combined_df = new_df

                # --- 4. 重複処理ロジック ---
                # 1. event_idを数値に変換（比較のため）
                combined_df['event_id_num'] = pd.to_numeric(combined_df['event_id'], errors='coerce')
                
                # 2. room_idでグルーピングし、event_id_numの最大値（新しいもの）を持つ行を選択
                #   - idxmax()は最大値を持つインデックスを返す
                #   - .loc[]でそのインデックスの行を抽出
                final_df = combined_df.loc[
                    combined_df.groupby('room_id')['event_id_num'].idxmax()
                ]
                
                # 3. 作業用列を削除し、最終的なCSV形式に整える
                final_df = final_df[['room_id', 'event_id']]

                st.subheader("📊 最終的なアップロードデータ（重複排除後）")
                st.dataframe(final_df)
                st.success(f"重複排除後、**{len(final_df)}** 件のユニークなルームIDが確定しました。")
                
                # FTPアップロード
                upload_ftp_file(ftp, final_df, FTP_FILE_PATH)

        except KeyError:
            st.error("❌ secrets.toml に [ftp] セクションが存在しないか、必要な情報が不足しています。")
        except Exception as e:
            st.error(f"❌ FTP接続または処理中に致命的なエラーが発生しました: {e}")

if __name__ == "__main__":
    main()