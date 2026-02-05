import os
import re
import pandas as pd
import streamlit as st
import pymysql

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Editor BI", layout="wide")
st.title("Editor de tabla MySQL (solo columnas con 'bi')")

# Variables de entorno sugeridas:
# MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "")

# ---- Ajustá estos defaults ----
DEFAULT_TABLE = os.getenv("MYSQL_TABLE", "")
DEFAULT_PK = os.getenv("MYSQL_PK", "id")  # puede ser "id" o "col1,col2"

# =========================
# HELPERS
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
    )

def is_bi_col(col_name: str) -> bool:
    return "bi" in (col_name or "").lower()

def quote_ident(name: str) -> str:
    # Escapa identificadores con backticks para evitar SQL injection en nombres
    if not re.match(r"^[A-Za-z0-9_]+$", name):
        raise ValueError(f"Identificador inválido: {name}")
    return f"`{name}`"

def fetch_df(table: str, limit: int):
    q = f"SELECT * FROM {quote_ident(table)} LIMIT %s"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q, (limit,))
            rows = cur.fetchall()
    return pd.DataFrame(rows)

def update_rows(table: str, pk_cols: list[str], bi_cols: list[str], original: pd.DataFrame, edited: pd.DataFrame):
    """
    Detecta cambios y actualiza solo columnas bi_cols, usando pk_cols como WHERE.
    """
    if original.empty:
        return 0

    # Alineamos índices por PK (recomendado)
    # Creamos una clave compuesta string para comparar
    def make_key(df: pd.DataFrame) -> pd.Series:
        return df[pk_cols].astype(str).agg("||".join, axis=1)

    orig = original.copy()
    edit = edited.copy()

    orig["_key"] = make_key(orig)
    edit["_key"] = make_key(edit)

    orig = orig.set_index("_key", drop=True)
    edit = edit.set_index("_key", drop=True)

    # Nos quedamos con claves comunes
    common_keys = orig.index.intersection(edit.index)
    orig = orig.loc[common_keys]
    edit = edit.loc[common_keys]

    updates = []
    for k in common_keys:
        row_orig = orig.loc[k]
        row_edit = edit.loc[k]

        changed_cols = []
        changed_vals = []
        for c in bi_cols:
            v0 = row_orig.get(c)
            v1 = row_edit.get(c)

            # Normalizamos NaN/None para comparar
            if pd.isna(v0): v0 = None
            if pd.isna(v1): v1 = None

            if v0 != v1:
                changed_cols.append(c)
                changed_vals.append(v1)

        if changed_cols:
            where_vals = [row_edit[pk] for pk in pk_cols]
            updates.append((changed_cols, changed_vals, where_vals))

    if not updates:
        return 0

    # Ejecutamos updates
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                for changed_cols, changed_vals, where_vals in updates:
                    set_sql = ", ".join([f"{quote_ident(c)}=%s" for c in changed_cols])
                    where_sql = " AND ".join([f"{quote_ident(pk)}=%s" for pk in pk_cols])
                    sql = f"UPDATE {quote_ident(table)} SET {set_sql} WHERE {where_sql}"
                    cur.execute(sql, tuple(changed_vals + where_vals))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return len(updates)

# =========================
# UI
# =========================
with st.sidebar:
    st.subheader("Conexión / tabla")
    st.caption("Usa variables de entorno o completá aquí.")
    host = st.text_input("Host", MYSQL_HOST)
    port = st.number_input("Port", value=MYSQL_PORT, step=1)
    user = st.text_input("User", MYSQL_USER)
    password = st.text_input("Password", MYSQL_PASSWORD, type="password")
    database = st.text_input("Database", MYSQL_DATABASE)
    table = st.text_input("Tabla", DEFAULT_TABLE)
    pk_raw = st.text_input("PK (una o varias, separadas por coma)", DEFAULT_PK)
    limit = st.number_input("LIMIT", min_value=1, value=200, step=50)

    st.divider()
    st.info("Solo se podrán editar columnas cuyo nombre contenga 'bi' (no distingue mayúsculas/minúsculas).")

# Refrescamos config de conexión (simplemente reasignamos globals)
MYSQL_HOST = host
MYSQL_PORT = int(port)
MYSQL_USER = user
MYSQL_PASSWORD = password
MYSQL_DATABASE = database

if not database or not table:
    st.warning("Completá Database y Tabla para continuar.")
    st.stop()

pk_cols = [c.strip() for c in pk_raw.split(",") if c.strip()]
if not pk_cols:
    st.error("Necesitás indicar una PK (ej: id).")
    st.stop()

# Cargar datos
col1, col2 = st.columns([1, 1])
with col1:
    refresh = st.button("🔄 Recargar", use_container_width=True)
with col2:
    save = st.button("💾 Guardar cambios", type="primary", use_container_width=True)

if "df_original" not in st.session_state or refresh:
    df = fetch_df(table, int(limit))
    st.session_state.df_original = df
    st.session_state.df_edited = df.copy()

df_original = st.session_state.df_original

if df_original.empty:
    st.info("La consulta devolvió 0 filas.")
    st.stop()

# Validar PK existe en el DF
missing_pk = [c for c in pk_cols if c not in df_original.columns]
if missing_pk:
    st.error(f"La PK indicada no existe en el resultado: {missing_pk}")
    st.stop()

bi_cols = [c for c in df_original.columns if is_bi_col(c)]
if not bi_cols:
    st.warning("No se detectaron columnas con 'bi' en el nombre. Nada será editable.")
st.caption(f"Columnas editables: {', '.join(bi_cols) if bi_cols else '(ninguna)'}")

# Config columnas: deshabilitar todas menos bi
col_config = {}
disabled_cols = [c for c in df_original.columns if c not in bi_cols]

edited = st.data_editor(
    st.session_state.df_edited,
    use_container_width=True,
    num_rows="fixed",
    disabled=disabled_cols,  # Streamlit >= 1.29 soporta lista de columnas
    key="editor",
)

st.session_state.df_edited = edited

# Guardar
if save:
    try:
        updated = update_rows(
            table=table,
            pk_cols=pk_cols,
            bi_cols=bi_cols,
            original=df_original,
            edited=edited,
        )
        st.success(f"Listo. Filas actualizadas: {updated}")
        # recargar para reflejar DB como source of truth
        df = fetch_df(table, int(limit))
        st.session_state.df_original = df
        st.session_state.df_edited = df.copy()
    except Exception as e:
        st.error(f"Error guardando cambios: {e}")
