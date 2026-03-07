import streamlit as st
from openai import OpenAI

1. 画面の基本設定
st.set_page_config(page_title="ナラティブ・アドバイザー", layout="centered")
st.title("📖 ナラティブ・ポリシー・アドバイザー")

2. サイドバーでの属性選択
st.sidebar.header("対象者の属性を選択")
age = st.sidebar.selectbox("年代", ["40代前半", "40代後半", "50代前半"])
emp = st.sidebar.selectbox("雇用形態", ["不本意非正規", "無業者", "その他"])
fam = st.sidebar.selectbox("家族構成", ["単身", "夫婦と子", "ひとり親", "親と同居"])

3. OpenAIクライアントの初期化
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

4. 物語生成のロジック（※先頭の空白4つが極めて重要です）
def generate_story():
    response = client.chat.completions.create(
model="gpt-4o",
messages=[
{"role": "system", "content": "政策アドバイザーとして300文字の物語を書いて。"},
{"role": "user", "content": f"属性：{age}, {emp}, {fam}"}
]
)
return response.choices[0].message.content

5. 生成ボタンと結果表示
if st.sidebar.button("物語を生成"):
    with st.spinner('生成中...'):
try:
story = generate_story()
st.subheader("生成された物語")
st.write(story)
except Exception as e:
st.error(f"エラー: {e}")
