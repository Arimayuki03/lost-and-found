from flask import Blueprint

common = Blueprint('common', __name__)

from . import check_user, email, found_items, lost_items, photo, token, announcement, carousel_image, search
