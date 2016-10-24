#!/usr/bin/env python
#
# deepzoom_server - Example web application for serving whole-slide images
#
# Copyright (c) 2010-2015 Carnegie Mellon University
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of version 2.1 of the GNU Lesser General Public License
# as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public
# License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
from datetime import datetime

from flask import Flask, abort, make_response, render_template, url_for,request, redirect,jsonify
from werkzeug.utils import secure_filename
import os

from io import BytesIO
import openslide
from openslide import ImageSlide, open_slide
from openslide.deepzoom import DeepZoomGenerator
from optparse import OptionParser
import re
from unicodedata import normalize
from os import listdir
from os.path import isfile, join

DEEPZOOM_SLIDE = None
DEEPZOOM_FORMAT = 'jpeg'
DEEPZOOM_TILE_SIZE = 254
DEEPZOOM_OVERLAP = 1
DEEPZOOM_LIMIT_BOUNDS = True
DEEPZOOM_TILE_QUALITY = 75
SLIDE_NAME = 'slide'


FILE_PATH = '/Users/vineeth/projects/Flask/imagezoom/CMU-1-JP2K-33005.svs'


from flask.ext.cors import CORS, cross_origin
app = Flask(__name__)
cors = CORS(app)
app.config.from_object(__name__)

app.config['CORS_HEADERS'] = 'Content-Type'

app.config.from_envvar('DEEPZOOM_TILER_SETTINGS', silent=True)
app.config['UPLOAD_FOLDER'] = '/home/ubuntu/imagezoom/media'
app.config['MAX_CONTENT_PATH'] = 1024*1024*1024
ACCESS_KEY = 'E4733D156B7F755A792E5EFBEE8D5'


ALLOWED_EXTENSIONS = set(['svs','ndpi','vms','vmu','scn','mrxs','tiff','svslide','bif'])


class PILBytesIO(BytesIO):
    def fileno(self):
        '''Classic PIL doesn't understand io.UnsupportedOperation.'''
        raise AttributeError('Not supported')


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS



def load_slide(filename):
    slidefile = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if slidefile is None:
        raise ValueError('No slide file specified')
    config_map = {
        'DEEPZOOM_TILE_SIZE': 'tile_size',
        'DEEPZOOM_OVERLAP': 'overlap',
        'DEEPZOOM_LIMIT_BOUNDS': 'limit_bounds',
    }
    opts = dict((v, app.config[k]) for k, v in config_map.items())
    slide = open_slide(slidefile)
    app.slides = {
        SLIDE_NAME: DeepZoomGenerator(slide, **opts)
    }
    app.associated_images = []
    app.slide_properties = slide.properties
    for name, image in slide.associated_images.items():
        app.associated_images.append(name)
        slug = slugify(name)
        app.slides[slug] = DeepZoomGenerator(ImageSlide(image), **opts)
    try:
        mpp_x = slide.properties[openslide.PROPERTY_NAME_MPP_X]
        mpp_y = slide.properties[openslide.PROPERTY_NAME_MPP_Y]
        app.slide_mpp = (float(mpp_x) + float(mpp_y)) / 2
    except (KeyError, ValueError):
        app.slide_mpp = 0


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            return redirect(request.url)
        if not file or not allowed_file(file.filename):
            return jsonify({"status":0,"message":"Unsuppored file format"})
        filename = str(datetime.now())+ secure_filename(file.filename)
        filename.replace(" ", "")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({"status":1,"name":filename})
#        return redirect(url_for('view_file',
#                                    filename=filename))
    return ""

@app.route('/names')
def names():
    path = app.config['UPLOAD_FOLDER']
    files = [f for f in listdir(path) if isfile(join(path, f))]
    return jsonify(files)

@app.route('/access_key')
def access_key():
    return jsonify(ACCESS_KEY)


@app.route('/delete')
def delete_file():
    key = request.args.get('access_key')
    if key != ACCESS_KEY:
        return jsonify({"status":1,"message":"Invalid Access key"})
    file_name = request.args.get('filename')
    full_path = os.path.join(app.config['UPLOAD_FOLDER'], file_name)
    if os.path.isfile(full_path):
        os.remove(full_path)
    return jsonify({"status":1,"message":"Success"})



@app.route('/view_file')
def view_file():

    filename = request.args.get('filename')
    load_slide(filename)
    print filename
    slide_url = url_for('dzi', slug=SLIDE_NAME)
    associated_urls = dict((name, url_for('dzi', slug=slugify(name)))
            for name in app.associated_images)
    return render_template('slide-multipane.html', slide_url=slide_url,
            associated=associated_urls, properties=app.slide_properties,
            slide_mpp=app.slide_mpp)


@app.route('/<slug>.dzi')
def dzi(slug):
    format = app.config['DEEPZOOM_FORMAT']
    try:
        resp = make_response(app.slides[slug].get_dzi(format))
        resp.mimetype = 'application/xml'
        return resp
    except KeyError:
        # Unknown slug
        abort(404)


@app.route('/<slug>_files/<int:level>/<int:col>_<int:row>.<format>')
def tile(slug, level, col, row, format):
    format = format.lower()
    if format != 'jpeg' and format != 'png':
        # Not supported by Deep Zoom
        abort(404)
    try:
        tile = app.slides[slug].get_tile(level, (col, row))
    except KeyError:
        # Unknown slug
        abort(404)
    except ValueError:
        # Invalid level or coordinates
        abort(404)
    buf = PILBytesIO()
    tile.save(buf, format, quality=app.config['DEEPZOOM_TILE_QUALITY'])
    resp = make_response(buf.getvalue())
    resp.mimetype = 'image/%s' % format
    return resp


def slugify(text):
    text = normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode()
    return re.sub('[^a-z0-9]+', '-', text)


if __name__ == '__main__':
    parser = OptionParser(usage='Usage: %prog [options] [slide]')
    parser.add_option('-B', '--ignore-bounds', dest='DEEPZOOM_LIMIT_BOUNDS',
                default=True, action='store_false',
                help='display entire scan area')
    parser.add_option('-c', '--config', metavar='FILE', dest='config',
                help='config file')
    parser.add_option('-d', '--debug', dest='DEBUG', action='store_true',
                help='run in debugging mode (insecure)')
    parser.add_option('-e', '--overlap', metavar='PIXELS',
                dest='DEEPZOOM_OVERLAP', type='int',
                help='overlap of adjacent tiles [1]')
    parser.add_option('-f', '--format', metavar='{jpeg|png}',
                dest='DEEPZOOM_FORMAT',
                help='image format for tiles [jpeg]')
    parser.add_option('-l', '--listen', metavar='ADDRESS', dest='host',
                default='127.0.0.1',
                help='address to listen on [127.0.0.1]')
    parser.add_option('-p', '--port', metavar='PORT', dest='port',
                type='int', default=5000,
                help='port to listen on [5000]')
    parser.add_option('-Q', '--quality', metavar='QUALITY',
                dest='DEEPZOOM_TILE_QUALITY', type='int',
                help='JPEG compression quality [75]')
    parser.add_option('-s', '--size', metavar='PIXELS',
                dest='DEEPZOOM_TILE_SIZE', type='int',
                help='tile size [254]')

    (opts, args) = parser.parse_args()
    # Load config file if specified
    if opts.config is not None:
        app.config.from_pyfile(opts.config)
    # Overwrite only those settings specified on the command line
    for k in dir(opts):
        if not k.startswith('_') and getattr(opts, k) is None:
            delattr(opts, k)
    app.config.from_object(opts)
    # Set slide file
    try:
        app.config['DEEPZOOM_SLIDE'] = FILE_PATH
    except IndexError:
        if app.config['DEEPZOOM_SLIDE'] is None:
            parser.error('No slide file specified')

    app.run(host=opts.host, port=opts.port, threaded=True)
