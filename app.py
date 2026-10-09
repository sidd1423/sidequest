import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # loads variables from .env

st.set_page_config(page_title="Sidequest", page_icon="🗺️", layout="centered")

st.title("Sidequest")
st.write("Your Streamlit app is up and running. Edit `app.py` to get started.")

name = st.text_input("What's your name?")
if name:
    st.success(f"Welcome to the sidequest, {name}!")
