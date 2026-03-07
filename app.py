import streamlit as st
from openai import OpenAI

画面設定
st.title("📖 ナラティブ・ポリシー・アドバイザー")
st.caption("データと物語を繋ぎ、行政の解像度をアップデートする")

サイドバーの設定
st.sidebar.header("属性を選択してください")
age = st.sidebar.selectbox("年代", ["40代前半", "40代後半", "50代前半"])
employment = st.sidebar.selectbox("雇用形態", ["不本意非正規（事務アシスタント等）", "無業者", "その他"])
family = st.sidebar.selectbox("家族構成", ["単身", "夫婦と子", "ひとり親", "親と同居（介護等）"])

OpenAIクライアントの初期化（SecretsからAPIキーを取得）
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

def generate_story():
# 最新のOpenAIライブラリ（v1.0以降）に対応した記述
response = client.chat.completions.create(
model="gpt-4o",
messages=[
{"role": "system", "content": "あなたは熟練の政策アドバイザーです。属性に基づき、統計データの背景にある300文字程度の切実な物語を書いてください。"},
{"role": "user", "content": f"年代:{age}, 雇用:{employment}, 家族:{family}"}
],
max_tokens=500
)
# 結果のテキスト部分のみを抽出
return response.choices[0].message.content

ボタンが押された時の処理
if st.sidebar.button("物語を生成"):
with st.spinner('ナラティブを生成中...'):
try:
# 物語生成関数の呼び出し
story = generate_story()
