import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from openai import OpenAI


# =========================
# 基本設定
# =========================
st.set_page_config(page_title="ナラティブ・ポリシー・アドバイザー", layout="wide")
st.title("📖 ナラティブ・ポリシー・アドバイザー")
st.caption("東京都オープンデータを根拠として、対象者像・物語・ニーズ・政策仮説を生成します。")

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
CURRENT_YEAR = datetime.now().year

# 東京都オープンデータ CKAN API
CKAN_API = "https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_search"


# =========================
# ユーティリティ
# =========================
def safe_json_load(text: str) -> dict:
    """LLM返答からJSONだけを安全に取り出す"""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError("JSONの解析に失敗しました。返答形式を確認してください。")


def birth_cohort_label(start_year: int, end_year: int) -> str:
    age_low = CURRENT_YEAR - end_year
    age_high = CURRENT_YEAR - start_year
    return f"{start_year}〜{end_year}年生（{age_low}〜{age_high}歳相当）"


def derived_age_category(start_year: int, end_year: int) -> str:
    age_low = CURRENT_YEAR - end_year
    age_high = CURRENT_YEAR - start_year
    mid = (age_low + age_high) / 2

    if 40 <= mid < 45:
        return "40代前半"
    elif 45 <= mid < 50:
        return "40代後半"
    elif 50 <= mid < 55:
        return "50代前半"
    return "就職氷河期世代"


def to_official_age_band(start_year: int, end_year: int) -> str:
    """
    東京都労働力統計の年齢階級に近似させる
    """
    age_low = CURRENT_YEAR - end_year
    age_high = CURRENT_YEAR - start_year
    mid = (age_low + age_high) / 2

    if mid < 45:
        return "35～44歳"
    elif mid < 55:
        return "45～54歳"
    return "55～64歳"


def first_text_column(df: pd.DataFrame) -> str:
    for col in df.columns:
        if df[col].dtype == object:
            return col
    return df.columns[0]


def normalize_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].astype(str).str.replace(",", "", regex=False)
            out[col] = pd.to_numeric(out[col], errors="ignore")
    return out


def load_csv_flexible(url: str) -> pd.DataFrame:
    """
    東京都のCSVは文字コードゆれがあるため複数候補で読む
    """
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    encodings = ["utf-8-sig", "cp932", "shift_jis", "utf-8"]
    last_error = None

    for enc in encodings:
        try:
            return pd.read_csv(pd.io.common.BytesIO(response.content), encoding=enc)
        except Exception as e:
            last_error = e

    raise last_error


def format_thousand_persons(value):
    try:
        return f"{float(value):.1f}千人"
    except Exception:
        return "不明"


# =========================
# 東京都オープンデータ検索
# =========================
@st.cache_data(ttl=60 * 60 * 12)
def search_tokyo_catalog(query: str, rows: int = 10):
    params = {"q": query, "rows": rows}
    response = requests.get(CKAN_API, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        return []

    return data["result"]["results"]


@st.cache_data(ttl=60 * 60 * 12)
def get_dataset_resources_by_title_keyword(title_keyword: str):
    results = search_tokyo_catalog(title_keyword, rows=10)
    if not results:
        return None

    for ds in results:
        title = (ds.get("title") or "").replace(" ", "")
        if title_keyword.replace(" ", "")[:4] in title:
            return ds
    return results[0]


def get_resource_url(dataset: dict, resource_name_keyword: str):
    if not dataset:
        return None, None

    for res in dataset.get("resources", []):
        name = res.get("name") or ""
        if resource_name_keyword in name:
            return res.get("url"), name

    return None, None


# =========================
# 参照データ定義
# 規模感推計
# =========================
@st.cache_data(ttl=60 * 60 * 12)
def get_labor_force_dataset():
    ds = get_dataset_resources_by_title_keyword("東京の労働力 統計データ（令和4年平均）")
    if ds:
        return ds
    return get_dataset_resources_by_title_keyword("東京の労働力 統計データ（令和3年平均）")


def detect_age_column(df: pd.DataFrame, official_age_band: str):
    candidates = []
    for col in df.columns:
        s = str(col)
        if official_age_band in s and "実数" in s:
            candidates.append(col)

    if not candidates:
        for col in df.columns:
            if official_age_band in str(col):
                candidates.append(col)

    return candidates[0] if candidates else None


def detect_row(df: pd.DataFrame, keywords):
    text_col = first_text_column(df)
    series = df[text_col].astype(str)
    for kw in keywords:
        hit = df[series.str.contains(kw, na=False)]
        if not hit.empty:
            return hit.iloc[0]
    return None


def estimate_scale(selected_gender: str, birth_start: int, birth_end: int, employment: str):
    ds = get_labor_force_dataset()
    if not ds:
        return {
            "summary": "東京都オープンデータから規模感を取得できませんでした。",
            "details": [],
            "source_links": []
        }

    official_age_band = to_official_age_band(birth_start, birth_end)

    if selected_gender == "男性":
        age_table_kw = "第３表 年齢階級別就業状態（男）"
    elif selected_gender == "女性":
        age_table_kw = "第３表 年齢階級別就業状態（女）"
    else:
        age_table_kw = "第３表 年齢階級別就業状態（男女計）"

    age_url, age_name = get_resource_url(ds, age_table_kw)
    emp_url, emp_name = get_resource_url(ds, "第８表 年齢階級、雇用形態別の役員を除く雇用者数")

    details = []
    source_links = []

    try:
        if age_url:
            df_age = normalize_numeric_columns(load_csv_flexible(age_url))
            age_col = detect_age_column(df_age, official_age_band)

            if age_col:
                labor_force = detect_row(df_age, ["労働力人口"])
                employed = detect_row(df_age, ["就業者", "有業者"])
                unemployed = detect_row(df_age, ["完全失業者", "失業者"])
                non_labor = detect_row(df_age, ["非労働力人口"])

                if labor_force is not None:
                    details.append({
                        "label": f"{official_age_band}の労働力人口",
                        "value": format_thousand_persons(labor_force.get(age_col))
                    })
                if employed is not None:
                    details.append({
                        "label": f"{official_age_band}の就業者",
                        "value": format_thousand_persons(employed.get(age_col))
                    })
                if unemployed is not None:
                    details.append({
                        "label": f"{official_age_band}の完全失業者",
                        "value": format_thousand_persons(unemployed.get(age_col))
                    })
                if non_labor is not None:
                    details.append({
                        "label": f"{official_age_band}の非労働力人口",
                        "value": format_thousand_persons(non_labor.get(age_col))
                    })

            source_links.append({
                "name": age_name or "年齢階級別就業状態",
                "url": age_url
            })
    except Exception:
        pass

    try:
        if emp_url and employment in ["正規", "非正規"]:
            df_emp = normalize_numeric_columns(load_csv_flexible(emp_url))
            age_col = detect_age_column(df_emp, official_age_band)

            if age_col:
                if employment == "正規":
                    row = detect_row(df_emp, ["正規", "正規の職員", "正社員"])
                else:
                    row = detect_row(df_emp, ["非正規", "パート", "アルバイト", "契約社員", "派遣"])

                if row is not None:
                    details.append({
                        "label": f"{official_age_band}の{employment}雇用者",
                        "value": format_thousand_persons(row.get(age_col))
                    })

            source_links.append({
                "name": emp_name or "雇用形態別雇用者数",
                "url": emp_url
            })
    except Exception:
        pass

    if employment == "無業者":
        details.append({
            "label": "補足",
            "value": "無業者は直接の単一統計値が乏しいため、完全失業者と非労働力人口を併せて政策検討用の参考規模として解釈します。"
        })
    elif employment == "休職中":
        details.append({
            "label": "補足",
            "value": "休職中の直接統計は乏しいため、就業者数・雇用形態・健康制約を組み合わせて解釈します。"
        })

    summary = (
        f"東京都の公式オープンデータをもとに、{official_age_band}の近似階級で規模感を表示しています。"
        "生年5年区分と統計表の年齢階級は一致しないため、政策検討用の参考値です。"
    )

    return {
        "summary": summary,
        "details": details,
        "source_links": source_links
    }


# =========================
# LLMプロンプト
# =========================
def build_structured_case_prompt(user_context, scale, references):
    return f"""
あなたは東京都の就職氷河期世代支援を担当する政策設計アナリストです。
以下の属性、前提条件、東京都オープンデータの参照情報、規模感推計を踏まえて、
「ありきたりな支援策の列挙」ではなく、
当事者の詰まりポイントが具体的に見える構造化ケースをJSONで作成してください。

【対象者属性】
- 性別: {user_context['gender']}
- 生年区分: {user_context['birth_label']}
- 年代カテゴリ: {user_context['age_category']}
- 雇用形態: {user_context['employment']}
- 家族構成: {user_context['family']}
- 最終学歴: {user_context['education']}
- 健康/就労制約: {user_context['health_constraint']}
- ケア責任: {user_context['care_responsibility']}
- 住居状況: {user_context['housing']}
- デジタル利用環境: {user_context['digital_access']}
- 相談先の有無: {user_context['support_network']}

【追加条件】
- 支援方法: {", ".join(user_context['support_methods']) if user_context['support_methods'] else "指定なし"}
- 支援期間: {user_context['support_period']}
- 政策目標: {user_context['policy_goal']}
- 当事者の制約: {", ".join(user_context['constraints']) if user_context['constraints'] else "指定なし"}

【規模感推計】
{json.dumps(scale, ensure_ascii=False, indent=2)}

【参照データ】
{json.dumps(references, ensure_ascii=False, indent=2)}

【重要な指示】
- 属性の言い換えは禁止
- 「どんな日常上の詰まりがあるか」を具体化する
- 支援策を先に書かず、まず詰まりポイントを特定する
- 東京都オープンデータから読めること / 読めないことを分ける
- 課題は心理、制度、家計、健康、家族責任、移動、情報アクセスなど複数軸で捉える
- 陳腐な表現（不安を抱えている、悩んでいる、支援が必要、など）の多用は禁止
- 生活場面が浮かぶ具体性を持たせる

以下のJSONのみを返してください:

{{
  "data_observations": [
    {{
      "source": "参照データ名",
      "insight": "データから読めること",
      "implication": "人物像や課題設定にどう効くか"
    }}
  ],
  "persona_core": {{
    "current_state": "現在の生活状況を具体的に",
    "pain_points": ["日常の詰まり1", "日常の詰まり2", "日常の詰まり3"],
    "blocked_by": ["制度・環境・心理的な障壁1", "障壁2", "障壁3"],
    "latent_needs": ["表面化していないニーズ1", "ニーズ2", "ニーズ3"]
  }},
  "story_seed": {{
    "main_tension": "この人の核心的な葛藤",
    "turning_point": "政策が介入すべき転機",
    "why_this_case": "なぜ東京都の政策論点として意味があるか"
  }},
  "issue_tags": ["...", "..."],
  "data_tags": ["...", "..."],
  "evidence_trace": [
    {{
      "data_source": "参照データ名",
      "used_for": "どの設定に使ったか"
    }}
  ],
  "cautions": ["推定上の注意1", "推定上の注意2"]
}}
""".strip()


def build_story_prompt(structured_case, user_context):
    return f"""
あなたは優れたノンフィクションライター兼政策分析者です。
以下の構造化ケースをもとに、属性の説明ではなく、
生活の手触りと政策上の論点が立ち上がる短い物語と政策仮説をJSONで返してください。

【構造化ケース】
{json.dumps(structured_case, ensure_ascii=False, indent=2)}

【対象者属性】
- 性別: {user_context['gender']}
- 生年区分: {user_context['birth_label']}
- 雇用形態: {user_context['employment']}
- 家族構成: {user_context['family']}

【指示】
- 物語は300〜450文字
- 属性の説明文にしない
- 1日の場面、迷い、諦め、対人関係、制度との距離感などが見えるようにする
- “かわいそう”に寄せず、現実の詰まりを描く
- 政策仮説は一般論ではなく、ボトルネック仮説にする
- 仮説ごとに「なぜそう考えるか」を付ける
- 仮説は、窓口設計、支援順序、対象者抽出、制度連携、評価指標などの型を意識する

以下のJSONのみを返してください:

{{
  "story": "...",
  "needs": ["...", "...", "..."],
  "policy_hypotheses": [
    {{
      "type": "窓口設計仮説",
      "hypothesis": "...",
      "why": "..."
    }},
    {{
      "type": "支援順序仮説",
      "hypothesis": "...",
      "why": "..."
    }},
    {{
      "type": "制度連携仮説",
      "hypothesis": "...",
      "why": "..."
    }}
  ]
}}
""".strip()


def generate_case_and_story(user_context, references, scale):
    # Step1: 構造化ケース
    prompt1 = build_structured_case_prompt(user_context, scale, references)
    resp1 = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.8,
        messages=[
            {
                "role": "system",
                "content": "あなたは政策設計と社会課題の構造化に強いアシスタントです。必ずJSONのみを返してください。"
            },
            {"role": "user", "content": prompt1}
        ]
    )
    structured_case = safe_json_load(resp1.choices[0].message.content)

    # Step2: 物語・ニーズ・政策仮説
    prompt2 = build_story_prompt(structured_case, user_context)
    resp2 = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.9,
        messages=[
            {
                "role": "system",
                "content": "あなたは具体的な人物描写と政策仮説立案に強いアシスタントです。必ずJSONのみを返してください。"
            },
            {"role": "user", "content": prompt2}
        ]
    )
    story_block = safe_json_load(resp2.choices[0].message.content)

    merged = {
        **structured_case,
        **story_block
    }
    return merged


# =========================
# UI: サイドバー
# =========================
st.sidebar.header("対象者の属性を選択")

gender = st.sidebar.selectbox("① 性別", ["回答しない", "女性", "男性"])

birth_options = {
    birth_cohort_label(1980, 1984): (1980, 1984),
    birth_cohort_label(1975, 1979): (1975, 1979),
    birth_cohort_label(1970, 1974): (1970, 1974),
# 現在設定の表示
# =========================
st.subheader("現在の設定")
col1, col2 = st.columns(2)

with col1:
    st.write(f"**性別**: {gender}")
    st.write(f"**生年区分**: {birth_selected_label}")
    st.write(f"**年代カテゴリ**: {age_category}")
    st.write(f"**雇用形態**: {employment}")
    st.write(f"**家族構成**: {family}")

with col2:
    st.write(f"**最終学歴**: {education}")
    st.write(f"**健康/就労制約**: {health_constraint}")
    st.write(f"**ケア責任**: {care_responsibility}")
    st.write(f"**住居状況**: {housing}")
    st.write(f"**デジタル利用環境**: {digital_access}")
    st.write(f"**相談先**: {support_network}")

st.markdown("---")


# =========================
# 生成ボタン
# =========================
if st.button("物語を生成"):
    with st.spinner("東京都オープンデータを参照しながら生成中..."):
        try:
            references = build_reference_catalog()

            user_context = {
                "gender": gender,
                "birth_label": birth_selected_label,
                "age_category": age_category,
                "employment": employment,
                "family": family,
                "education": education,
                "health_constraint": health_constraint,
                "care_responsibility": care_responsibility,
                "housing": housing,
                "digital_access": digital_access,
                "support_network": support_network,
                "support_methods": support_methods,
                "support_period": support_period,
                "policy_goal": policy_goal,
                "constraints": constraints,
            }

            scale = estimate_scale(gender, birth_start, birth_end, employment)
            result = generate_case_and_story(user_context, references, scale)

            # -------------------------
            # 物語
            # -------------------------
            st.subheader("生成された物語")
            st.write(result.get("story", ""))

            # -------------------------
            # データから見た前提
            # -------------------------
            st.markdown("---")
            st.markdown("### 東京都オープンデータから見た前提")
            for obs in result.get("data_observations", []):
                st.markdown(f"**出典**: {obs.get('source', '')}")
                st.markdown(f"- 読み取れること: {obs.get('insight', '')}")
                st.markdown(f"- 今回の人物設定への反映: {obs.get('implication', '')}")

            # -------------------------
            # 主人公を置いた理由
            # -------------------------
            seed = result.get("story_seed", {})
            if seed:
                st.markdown("---")
                st.markdown("### この主人公を置いた理由")
                st.markdown(f"- **核心的な葛藤**: {seed.get('main_tension', '')}")
                st.markdown(f"- **介入すべき転機**: {seed.get('turning_point', '')}")
                st.markdown(f"- **政策論点としての意味**: {seed.get('why_this_case', '')}")

            # -------------------------
            # ペルソナの詰まり
            # -------------------------
            persona_core = result.get("persona_core", {})
            if persona_core:
                st.markdown("---")
                st.markdown("### 構造化された人物像")
                st.markdown(f"**現在の生活状況**: {persona_core.get('current_state', '')}")

                st.markdown("**日常の詰まり**")
                for item in persona_core.get("pain_points", []):
                    st.markdown(f"- {item}")

                st.markdown("**詰まりを強める障壁**")
                for item in persona_core.get("blocked_by", []):
                    st.markdown(f"- {item}")

                st.markdown("**潜在ニーズ**")
                for item in persona_core.get("latent_needs", []):
                    st.markdown(f"- {item}")

            # -------------------------
            # ニーズと政策仮説
            # -------------------------
            col3, col4 = st.columns(2)

            with col3:
                st.markdown("### 主人公のニーズ")
                for n in result.get("needs", []):
                    st.markdown(f"- {n}")

                st.markdown("### 課題タグ")
                issue_tags = result.get("issue_tags", [])
                if issue_tags:
                    st.caption(" / ".join([f"#{t}" for t in issue_tags]))

            with col4:
                st.markdown("### 政策仮説")
                for h in result.get("policy_hypotheses", []):
                    st.markdown(f"**{h.get('type', '仮説')}**")
                    st.markdown(f"- 仮説: {h.get('hypothesis', '')}")
                    st.markdown(f"- 根拠: {h.get('why', '')}")

                st.markdown("### データタグ")
                data_tags = result.get("data_tags", [])
                if data_tags:
                    st.caption(" / ".join([f"#{t}" for t in data_tags]))

            # -------------------------
            # 規模感
            # -------------------------
            st.markdown("---")
            st.markdown("### 人口分布・該当当事者の規模感（簡易推計）")
            st.info(scale.get("summary", ""))

            if scale.get("details"):
                for d in scale["details"]:
                    st.markdown(f"- **{d['label']}**: {d['value']}")
            else:
                st.write("該当する規模感を自動推計できませんでした。参照リンクをご確認ください。")

            # -------------------------
            # どのデータをどこに使ったか
            # -------------------------
            trace = result.get("evidence_trace", [])
            if trace:
                st.markdown("---")
                st.markdown("### どのデータをどこに使ったか")
                for t in trace:
                    st.markdown(f"- **{t.get('data_source', '')}** → {t.get('used_for', '')}")

            # -------------------------
            # 解釈上の注意
            # -------------------------
            cautions = result.get("cautions", [])
            if cautions:
                st.markdown("---")
                st.markdown("### 解釈上の注意")
                for c in cautions:
                    st.markdown(f"- {c}")

            # -------------------------
            # 参照した東京都オープンデータ
            # -------------------------
            st.markdown("---")
            st.markdown("### 参照した東京都オープンデータ")
            for ref in references:
                st.markdown(f"**[{ref['name']}]({ref['url']})**")
                st.write(ref["why"])
                st.caption(
                    "データタグ: "
                    + " / ".join([f"#{x}" for x in ref["data_tags"]])
                    + "　　課題タグ: "
                    + " / ".join([f"#{x}" for x in ref["issue_tags"]])
                )

            if scale.get("source_links"):
                st.markdown("### 規模感推計に使用したCSVリソース")
                for src in scale["source_links"]:
                    st.markdown(f"- [{src['name']}]({src['url']})")

        except Exception as e:
            st.error(f"エラー: {e}")
