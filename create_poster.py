#!/usr/bin/env python

import appdirs
import argparse
import datetime
import gpxpy
import hashlib
import json
import math
import os
import shutil
import svgwrite

__app_name__ = "create_poster"
__app_author__ = "flopp.net"


class Track:
    def __init__(self):
        self.file_names = []
        self.polylines = []
        self.start_time = None
        self.end_time = None
        self.length = 0
        self.highlight = False

    def load_gpx(self, file_name):
        checksum = hashlib.sha256(open(file_name, 'rb').read()).hexdigest()
        cache_dir = os.path.join(appdirs.user_cache_dir(__app_name__, __app_author__), "tracks")
        cache_file = os.path.join(cache_dir, checksum + ".json")

        if os.path.isfile(cache_file):
            print("cached")
            try:
                self.load_cache(cache_file)
                self.file_names = [os.path.basename(file_name)]
            except Exception as e:
                print("Failed to load cached track: {}".format(e))
                self.load_gpx_no_cache(file_name)
        else:
            self.load_gpx_no_cache(file_name)

    def load_gpx_no_cache(self, file_name):
        self.file_names = [os.path.basename(file_name)]
        with open(file_name, 'r') as file:
            gpx = gpxpy.parse(file)
            b = gpx.get_time_bounds()
            self.start_time = b[0]
            self.end_time = b[1]
            self.length = gpx.length_2d()
            gpx.simplify()
            for t in gpx.tracks:
                for s in t.segments:
                    line = [(p.latitude, p.longitude) for p in s.points]
                    self.polylines.append(line)
        checksum = hashlib.sha256(open(file_name, 'rb').read()).hexdigest()
        cache_dir = os.path.join(appdirs.user_cache_dir(__app_name__, __app_author__), "tracks")
        cache_file = os.path.join(cache_dir, checksum + ".json")
        self.store_cache(cache_file)

    def set_is_highlight(self, b):
        self.highlight = b

    def append(self, other):
        self.end_time = other.end_time
        self.polylines.extend(other.polylines)
        self.length += other.length
        self.file_names.extend(other.file_names)
        self.highlight = self.highlight or other.highlight

    def load_cache(self, cache_file_name):
        with open(cache_file_name) as data_file:
            data = json.load(data_file)
            self.start_time = datetime.datetime.strptime(data["start"], "%Y-%m-%d %H:%M:%S")
            self.end_time = datetime.datetime.strptime(data["end"], "%Y-%m-%d %H:%M:%S")
            self.length = float(data["length"])
            self.polylines = []
            for data_line in data["segments"]:
                self.polylines.append([(float(d["lat"]), float(d["lng"])) for d in data_line])

    def store_cache(self, cache_file_name):
        dir = os.path.dirname(cache_file_name)
        if not os.path.isdir(dir):
            os.makedirs(dir)
        with open(cache_file_name, 'w') as json_file:
            lines_data = []
            for line in self.polylines:
                lines_data.append([{"lat": lat, "lng": lng} for (lat, lng) in line])
            data = {
                "start": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end": self.end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "length": self.length,
                "segments": lines_data
            }
            json.dump(data, json_file)


def clear_cache():
    cache_dir = os.path.join(appdirs.user_cache_dir(__app_name__, __app_author__), "tracks")
    if os.path.isdir(cache_dir):
        print("Removing cache dir: {}".format(cache_dir))
        try:
            shutil.rmtree(cache_dir)
        except OSError as e:
            print("Failed: {}".format(e))


def list_gpx_files(base_dir):
    base_dir = os.path.abspath(base_dir)
    if not os.path.isdir(base_dir):
        raise Exception("Not a directory: {}".format(base_dir))
    for name in os.listdir(base_dir):
        path_name = os.path.join(base_dir, name)
        if name.endswith(".gpx") and os.path.isfile(path_name):
            yield path_name


def load_tracks(base_dir, year, highlight_filenames):
    min_length = 1000

    tracks = []
    file_names = [x for x in list_gpx_files(base_dir)]
    for (index, file_name) in enumerate(file_names):
        print("loading file {}/{}".format(index, len(file_names)))
        try:
            t = Track()
            t.load_gpx(file_name)

            if os.path.basename(file_name) in highlight_filenames:
                t.set_is_highlight(True)

            if t.length == 0:
                print("{}: skipping empty track".format(file_name))
            elif not t.start_time:
                print("{}: skipping track without start time".format(file_name))
            elif t.start_time.year != year:
                print("{}: skipping track with wrong year {}".format(file_name, t.start_time.year))
            else:
                tracks.append(t)
        except Exception as e:
            print("{}: error while parsing GPX file; {}".format(file_name, e))

    # sort tracks by start time
    sorted_tracks = sorted(tracks, key=lambda t: t.start_time)

    # merge tracks that took place within one hour
    merged_tracks = []
    last_end_time = None
    for t in sorted_tracks:
        if last_end_time is None:
            merged_tracks.append(t)
        else:
            dt = (t.start_time - last_end_time).total_seconds()
            if 0 < dt < 3600:
                print("Merging track with previous, due to time distance of {}s.".format(dt))
                merged_tracks[-1].append(t)
            else:
                merged_tracks.append(t)
        last_end_time = t.end_time

    # filter out tracks with length < min_length
    return [t for t in merged_tracks if t.length >= min_length]


# mercator projection
def latlng2xy(lat, lng):
    return lng/180+1, 0.5-math.log(math.tan(math.pi/4*(1+lat/90)))/math.pi


def compute_bounds(polylines):
    min_x = None
    max_x = None
    min_y = None
    max_y = None
    for line in polylines:
        for (x, y) in line:
            if min_x is None:
                min_x = x
                max_x = x
                min_y = y
                max_y = y
            else:
                min_x = min(x, min_x)
                max_x = max(x, max_x)
                min_y = min(y, min_y)
                max_y = max(y, max_y)
    return min_x, min_y, max_x, max_y


def draw_track(track, drawing, x_offset, y_offset, width, height, color):
    # compute mercator projection of track segments
    lines = []
    for polyline in track.polylines:
        lines.append([latlng2xy(lat, lng) for (lat, lng) in polyline])

    # compute bounds
    (min_x, min_y, max_x, max_y) = compute_bounds(lines)
    d_x = max_x - min_x
    d_y = max_y - min_y

    # compute scale
    scale = width/d_x
    if width/height > d_x/d_y:
        scale = height/d_y

    # compute offsets such that projected track is centered in its rect
    x_offset += 0.5 * width - 0.5 * scale * d_x
    y_offset += 0.5 * height - 0.5 * scale * d_y

    scaled_lines = []
    for line in lines:
        scaled_line = []
        for (x, y) in line:
            scaled_x = x_offset + scale * (x - min_x)
            scaled_y = y_offset + scale * (y - min_y)
            scaled_line.append((scaled_x, scaled_y))
        scaled_lines.append(scaled_line)

    for line in scaled_lines:
        drawing.add(drawing.polyline(points=line, stroke=color, fill='none', stroke_width=0.5, stroke_linejoin='round', stroke_linecap='round'))


def compute_lengths(tracks):
    min_length = -1
    max_length = -1
    total_length = 0
    for t in tracks:
        total_length += t.length
        if min_length < 0 or t.length < min_length:
            min_length = t.length
        if max_length < 0 or t.length > max_length:
            max_length = t.length
    return 0.001*total_length, 0.001*total_length/len(tracks), 0.001*min_length, 0.001*max_length


def compute_grid(count, width, height):
    min_waste = -1
    best_size = -1
    for x in range(1, width):
        s = width/x
        waste = width*height - count*s*s
        if waste < 0:
            continue
        if min_waste < 0 or waste < min_waste:
            min_waste = waste
            best_size = s
    count_x = width/best_size
    count_y = count // count_x
    if count % count_x > 0:
        count_y += 1
    spacing_y = (height - count_y * best_size) / count_y

    return best_size, count_x, count_y, spacing_y


def poster(tracks, title, year, athlete_name, output, colors):
    (total_length, average_length, min_length, max_length) = compute_lengths(tracks)

    w = 200
    h = 300
    d = svgwrite.Drawing(output, ('{}mm'.format(w), '{}mm'.format(h)))
    d.viewbox(0, 0, w, h)
    d.add(d.rect((0, 0), (w, h), fill=colors['background']))

    d.add(d.text(title, insert=(10, 20), fill=colors['text'], style="font-size:12px; font-family:Arial; font-weight:bold;"))
    d.add(d.text("YEAR", insert=(10, h-20), fill=colors['text'], style="font-size:4px; font-family:Arial"))
    d.add(d.text("{}".format(year), insert=(10, h-10), fill=colors['text'], style="font-size:9px; font-family:Arial"))
    d.add(d.text("ATHLETE", insert=(40, h-20), fill=colors['text'], style="font-size:4px; font-family:Arial"))
    d.add(d.text(athlete_name, insert=(40, h-10), fill=colors['text'], style="font-size:9px; font-family:Arial"))
    d.add(d.text("STATISTICS", insert=(120, h-20), fill=colors['text'], style="font-size:4px; font-family:Arial"))
    d.add(d.text("Runs: {}".format(len(tracks)), insert=(120, h-15), fill=colors['text'], style="font-size:3px; font-family:Arial"))
    d.add(d.text("Weekly: {:.1f}".format(len(tracks)/52), insert=(120, h-10), fill=colors['text'], style="font-size:3px; font-family:Arial"))
    d.add(d.text("Total: {:.1f} km".format(total_length), insert=(139, h-15), fill=colors['text'], style="font-size:3px; font-family:Arial"))
    d.add(d.text("Avg: {:.1f} km".format(average_length), insert=(139, h-10), fill=colors['text'], style="font-size:3px; font-family:Arial"))
    d.add(d.text("Min: {:.1f} km".format(min_length), insert=(167, h-15), fill=colors['text'], style="font-size:3px; font-family:Arial"))
    d.add(d.text("Max: {:.1f} km".format(max_length), insert=(167, h-10), fill=colors['text'], style="font-size:3px; font-family:Arial"))

    tracks_w = w - 20
    tracks_h = h - 30 - 30
    tracks_x = 10
    tracks_y = 30

    (size, count_x, count_y, spacing_y) = compute_grid(len(tracks), tracks_w, tracks_h)
    for (index, track) in enumerate(tracks):
        x = index % count_x
        y = index // count_x
        color = colors['highlight'] if track.highlight else colors['track']
        draw_track(track, d, tracks_x+(0.05 + x)*size, tracks_y+(0.05+y)*size+y*spacing_y, 0.9 * size, 0.9 * size, color)

    d.save()
    print("Wrote poster to {}".format(output))


def main():
    command_line_parser = argparse.ArgumentParser()
    command_line_parser.add_argument('--gpx-dir', dest='gpx_dir', metavar='DIR', type=str, default='.', help='Directory containing GPX files (default: current directory).')
    command_line_parser.add_argument('--year', metavar='YEAR', type=int, default=datetime.date.today().year-1, help='Filter tracks by year (default: past year)')
    command_line_parser.add_argument('--title', metavar='TITLE', type=str, default="My Tracks", help='Title to display (default: "My Tracks").')
    command_line_parser.add_argument('--athlete', metavar='NAME', type=str, default="John Doe", help='Athlete name to display (default: "John Doe").')
    command_line_parser.add_argument('--background-color', dest='background_color', metavar='COLOR', type=str, default='#222222', help='Background color of poster (default: "#222222").')
    command_line_parser.add_argument('--track-color', dest='track_color', metavar='COLOR', type=str, default='#4DD2FF', help='Color of tracks (default: "#4DD2FF").')
    command_line_parser.add_argument('--text-color', dest='text_color', metavar='COLOR', type=str, default='#FFFFFF', help='Color of text (default: "#FFFFFF").')
    command_line_parser.add_argument('--highlight', metavar='FILE', action='append', default=[], help='Highlight specified track file from the GPX directory; use multiple times to highlight multiple tracks.')
    command_line_parser.add_argument('--highlight-color', dest='highlight_color', metavar='COLOR', default='#FFFF00', help='Track highlighting color (default: "#FFFF00").')
    command_line_parser.add_argument('--output', metavar='FILE', type=str, default='poster.svg', help='Name of generated SVG image file (default: "poster.svg").')
    command_line_parser.add_argument('--clear-cache', dest='clear_cache', action='store_true', help='Clear the track cache.')
    command_line_args = command_line_parser.parse_args()

    print(command_line_args.highlight)
    if command_line_args.clear_cache:
        clear_cache()

    tracks = load_tracks(command_line_args.gpx_dir, command_line_args.year, command_line_args.highlight)
    if not tracks:
        raise Exception('No tracks found.')

    colors = {'background': command_line_args.background_color, 'track': command_line_args.track_color, 'highlight': command_line_args.highlight_color, 'text': command_line_args.text_color}
    poster(tracks, command_line_args.title, command_line_args.year, command_line_args.athlete, command_line_args.output, colors)


if __name__ == '__main__':
    main()