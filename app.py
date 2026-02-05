import re
import pandas as pd
import streamlit as st
import pymysql

# =========================
# CONFIG APP
# =========================
st.set_page_config(page_title="Editor BI", layout="wide")
st.title("Editor de atributos BI")

# =========================
# SECRETS
# =========================
MYSQL = st.secrets["mysql"]
APP = st.secrets["app"]

MYSQL_HOST = MYSQL["host"]
MYSQL_PORT = int(MYSQL.get("port", 3306))
MYSQL_USER = MYSQL["user"]
MYSQL_PASSWORD = MYSQL["password"]
MYSQL_DATABASE = MYSQL["database"]

TABLE = APP["table"]
PK_COLS = [c.strip() for c in APP["pk"].split(",")]
LIMIT = int(APP.get("limit", 200))

# =========================
# DB
# =========================
def get_conn():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )

def quote_ident(name: str) -> str:
    if not re.match(r"^[A-Za-z0-9_]+$", name):
        raise ValueError(f"Identificador inválido: {name}")
    return f"`{name}`"

def is_bi_col(col: str) -> bool:
    return "bi" in col.lower()

# =========================
# DATA
# =========================
@st.cache_data(show_spinner=False)
def load_data():
    sql = f"SELECT * FROM {quote_ident(TABLE)} LIMIT %s"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (LIMIT,))
            return pd.DataFrame(cur.fetchall())

def update_rows(df_old, df_new):
    bi_cols = [c for c in df_old.columns if is_bi_col(c)]
    updated = 0

    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                for _, r_old in df_old.iterrows():
                    r_new = df_new.loc[_]
                    sets, vals = [], []

                    for c in bi_cols:
                        if r_old[c] != r_new[c]:
                            sets.append(f"{quote_ident(c)}=%s")
                            vals.append(r_new[c])

                    if not sets:
                        continue

                    where = []
                    for pk in PK_COLS:
                        where.append(f"{quote_ident(pk)}=%s")
                        vals.append(r_old[pk])

                    sql = f"""
                        UPDATE {quote_ident(TABLE)}
                        SET {', '.join(sets)}
                        WHERE {' AND '.join(where)}
                    """
                    cur.execute(sql, tuple(vals))
                    updated += 1

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return updated

# =========================
# UI
# =========================
if "df_original" not in st.session_state:
    st.session_state.df_original = load_data()

df_original = st.session_state.df_original.copy()

bi_cols = [c for c in df_original.columns if is_bi_col(c)]
disabled_cols = [c for c in df_original.columns if c not in bi_cols]

st.caption(
    "Solo se permiten cambios en columnas que contienen **'bi'** en su nombre."
)

df_edit = st.data_editor(
    df_original,
    use_container_width=True,
    disabled=disabled_cols,
    num_rows="fixed",
)

col1, col2 = st.columns([1, 3])
with col1:
    if st.button("💾 Guardar cambios", type="primary"):
        updated = update_rows(st.session_state.df_original, df_edit)
        st.success(f"Filas actualizadas: {updated}")
        st.session_state.df_original = load_data()
        st.rerun()

with col2:
    if st.button("🔄 Recargar"):
        st.session_state.df_original = load_data()
        st.rerun()
