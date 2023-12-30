# MegaZoomQuilt.app

import csv
import random
from flask import Flask
from flask import render_template
from flask import request
from flask import session
from flask import abort, redirect, url_for

app = Flask(__name__)
app.secret_key = b'foobar'
app.debug=True

@app.route("/admin")
def admin():
    p={}
    p['page_title']='Admin'
    return render_template("admin.html", p=p)

@app.route("/")
def home():
    p={}
    p['page_title']='Home page!'
    return render_template("home.html", p=p)

