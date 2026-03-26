import streamlit as st
DB    = st.secrets["connections"]["snowflake"]["database"]
SC    = st.secrets["connections"]["snowflake"]["schema"]
STAGE = st.secrets["app"]["stage"]
MODEL = st.secrets["app"]["model"]

