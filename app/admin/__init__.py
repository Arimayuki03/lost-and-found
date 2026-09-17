from flask import Blueprint

admin = Blueprint('admin', __name__)

from . import announcement, carousel_image, feedback, found_items, lost_items, matching, stats, admins
