from flask import Flask, render_template, jsonify, request, send_file
import yt_dlp
# import subprocess # Not actively used, can be removed if truly not needed
# import json # Not actively used for loading, can be removed if truly not needed
import os
# import shutil # Not actively used, os.remove is used
import logging

app = Flask(__name__)

# Configure basic logging
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)


TEMP_DOWNLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_downloads')
if not os.path.exists(TEMP_DOWNLOAD_FOLDER):
    os.makedirs(TEMP_DOWNLOAD_FOLDER)
    app.logger.info(f"Created temporary download folder: {TEMP_DOWNLOAD_FOLDER}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/fetch_video_info', methods=['POST'])
def fetch_video_info():
    data = request.get_json()
    if not data or 'url' not in data:
        app.logger.warning("Fetch video info request with no JSON data or no URL.")
        return jsonify({'success': False, 'error': 'Request body must be JSON with a URL.'}), 400
        
    url = data.get('url')

    if not url:
        app.logger.warning("Fetch video info request with empty URL.")
        return jsonify({'success': False, 'error': 'URL is required'}), 400

    # Basic URL validation (yt-dlp will do more thorough checks)
    if not (url.startswith('http://') or url.startswith('https://')):
        app.logger.warning(f"Fetch video info request with invalid URL scheme: {url}")
        return jsonify({'success': False, 'error': 'Invalid URL format. Please include http:// or https://'}), 400


    ydl_opts = {
        'quiet': True,
        'extract_flat': 'discard_in_playlist', # More robust for single videos
        'force_generic_extractor': False,
        'skip_download': True,
        'nocheckcertificate': True, # Sometimes helps with SSL issues
        'retries': 2, # Retry downloads a couple of times
    }

    try:
        app.logger.info(f"Fetching video info for URL: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            title = info_dict.get('title', 'No title available')
            thumbnail = info_dict.get('thumbnail', None)
            
            if not title or not thumbnail: # Basic check for valid metadata
                 app.logger.warning(f"Could not extract essential video info (title/thumbnail) for URL: {url}")
                 return jsonify({'success': False, 'error': 'Could not retrieve essential video details. The video might be private, unavailable, or the URL is incorrect.'}), 404

            app.logger.info(f"Successfully fetched video info for URL: {url} - Title: {title}")
            return jsonify({'success': True, 'title': title, 'thumbnail': thumbnail})
            
    except yt_dlp.utils.DownloadError as de:
        app.logger.error(f"yt-dlp DownloadError while fetching info for {url}: {str(de)}")
        error_message = "Could not fetch video information."
        if "Unsupported URL" in str(de):
            error_message = "The provided URL is not supported or may be incorrect."
            return jsonify({'success': False, 'error': error_message}), 400
        elif "Video unavailable" in str(de) or "Private video" in str(de):
            error_message = "This video is unavailable or private."
            return jsonify({'success': False, 'error': error_message}), 404
        elif "unable to download webpage" in str(de).lower() or "network is unreachable" in str(de).lower():
            error_message = "Network error or content not accessible. Please check the URL and your connection."
            return jsonify({'success': False, 'error': error_message}), 502 # Bad Gateway, as we're proxying a request
        return jsonify({'success': False, 'error': error_message}), 500
        
    except Exception as e:
        app.logger.error(f"Generic exception while fetching video info for {url}: {str(e)}")
        return jsonify({'success': False, 'error': 'An unexpected server error occurred while fetching video info.'}), 500

@app.route('/download_video', methods=['POST'])
def download_video():
    data = request.get_json()
    if not data or 'url' not in data or 'format' not in data:
        app.logger.warning("Download request with missing JSON data, URL, or format.")
        return jsonify({'success': False, 'error': 'Request body must be JSON with URL and format.'}), 400

    url = data.get('url')
    download_format = data.get('format') 

    if not url or not download_format: # Should be caught by the above, but good for explicitness
        app.logger.warning("Download request with empty URL or format.")
        return jsonify({'success': False, 'error': 'URL and format are required.'}), 400
    
    if not (url.startswith('http://') or url.startswith('https://')):
        app.logger.warning(f"Download request with invalid URL scheme: {url}")
        return jsonify({'success': False, 'error': 'Invalid URL format. Please include http:// or https://'}), 400

    # Fetch title for filename (could also pass from frontend if already fetched)
    # This adds an extra call but ensures we have a title even if user skips preview
    # For optimization, frontend could send `title` if available.
    try:
        # Using simplified ydl_opts for just getting the title quickly
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'extract_flat': 'discard_in_playlist', 'nocheckcertificate': True}) as ydl:
            info_dict_for_title = ydl.extract_info(url, download=False)
            title = info_dict_for_title.get('title', 'downloaded_video')
            safe_title = "".join(c if c.isalnum() or c in [' ', '.', '_', '-'] else '_' for c in title)
            safe_title = safe_title[:60] # Limit length to avoid issues with long filenames
    except Exception as e:
        app.logger.warning(f"Error extracting title for download: {str(e)}. Using default filename.")
        safe_title = "downloaded_video"

    base_ydl_opts = {
        'quiet': True,
        'nocheckcertificate': True,
        'retries': 2,
        'merge_output_format': 'mp4', 
    }
    
    # Using a dynamic filename based on the format for the output template
    # This helps in predicting the filename more accurately
    file_suffix = f"_{download_format}" if download_format != "mp4" else "" # e.g. _mp3, _mp4_no_watermark
    if download_format == "mp4_no_watermark": # make suffix more readable
        file_suffix = "_no_watermark"

    # Construct the base for the output template, extension will be added by yt-dlp or postprocessor
    outtmpl_base = os.path.join(TEMP_DOWNLOAD_FOLDER, f"{safe_title}{file_suffix}")
    
    filepath = None # To store the path of the downloaded file

    specific_opts = {}
    expected_extension = '.mp4' # Default

    if download_format == 'mp4':
        specific_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': f'{outtmpl_base}.%(ext)s',
        }
    elif download_format == 'mp4_no_watermark':
        specific_opts = {
            # Attempt to get a version without watermark by format preference
            # This is not foolproof and depends on what the platform provides.
            'format': 'bv*[vcodec!=h265][ext=mp4]+ba[ext=m4a]/b[vcodec!=h265][ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': f'{outtmpl_base}.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
    elif download_format == 'mp3':
        expected_extension = '.mp3'
        specific_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192', # Bitrate for MP3
            }],
            'outtmpl': f'{outtmpl_base}.%(ext)s', # yt-dlp handles the .mp3 extension
        }
    else:
        app.logger.warning(f"Download request with invalid format: {download_format}")
        return jsonify({'success': False, 'error': 'Invalid format specified.'}), 400

    ydl_opts = {**base_ydl_opts, **specific_opts}

    try:
        app.logger.info(f"Starting download for URL: {url} with format: {download_format}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # The info dict from extract_info (when download=True) can sometimes lack details
            # or be complex to parse for the exact filename if multiple files are involved (not our case here).
            # So, we'll construct the expected filename.
            ydl.extract_info(url, download=True) 
            
            # Construct the most likely filepath. yt-dlp's outtmpl with %(ext)s should result in this.
            # For mp3, FFmpegExtractAudio postprocessor should set the .mp3 extension.
            # For mp4, merge_output_format or FFmpegVideoConvertor should ensure .mp4.
            filepath = f"{outtmpl_base}{expected_extension}"

            if not os.path.exists(filepath):
                # Fallback: if the primary expected file isn't there, check for common alternatives
                # e.g. if webm was downloaded instead of mp4 and conversion didn't happen as expected.
                app.logger.warning(f"Expected file {filepath} not found. Checking for alternatives...")
                found_alternative = False
                if expected_extension == '.mp4':
                    for alt_ext in ['.mkv', '.webm']: # Common video formats yt-dlp might download
                        alt_filepath = f"{outtmpl_base}{alt_ext}"
                        if os.path.exists(alt_filepath):
                            filepath = alt_filepath
                            app.logger.info(f"Found alternative file: {filepath}")
                            found_alternative = True
                            break
                if not found_alternative:
                    app.logger.error(f"Downloaded file could not be found at expected path {filepath} or common alternatives.")
                    # List directory contents for debugging
                    files_in_temp = os.listdir(TEMP_DOWNLOAD_FOLDER)
                    app.logger.debug(f"Contents of {TEMP_DOWNLOAD_FOLDER}: {files_in_temp}")
                    return jsonify({'success': False, 'error': 'Downloaded file not found or name mismatch after download.'}), 500
        
        app.logger.info(f"Successfully downloaded video: {filepath}")
        user_download_name = os.path.basename(filepath) 

        response = send_file(filepath, as_attachment=True, download_name=user_download_name)
        # Add headers to prevent caching for dynamic content
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    except yt_dlp.utils.DownloadError as de:
        app.logger.error(f"yt-dlp DownloadError for {url} (Format: {download_format}): {str(de)}")
        error_message = "Download failed."
        if "Unsupported URL" in str(de):
            error_message = "The provided URL is not supported or may be incorrect."
            return jsonify({'success': False, 'error': error_message}), 400
        elif "Video unavailable" in str(de) or "Private video" in str(de):
            error_message = "This video is unavailable or private, cannot download."
            return jsonify({'success': False, 'error': error_message}), 404
        elif "copyright" in str(de).lower():
            error_message = "This video is protected by copyright and cannot be downloaded."
            return jsonify({'success': False, 'error': error_message}), 451 # Unavailable For Legal Reasons
        elif "proxy" in str(de).lower() or " tűzfal " in str(de).lower(): # Hungarian for firewall
             error_message = "A proxy or firewall issue might be blocking the download."
             return jsonify({'success': False, 'error': error_message}), 502
        elif "no space left on device" in str(de).lower():
            error_message = "Server is out of space. Cannot complete download."
            return jsonify({'success': False, 'error': error_message}), 507 # Insufficient Storage
        return jsonify({'success': False, 'error': error_message}), 500
        
    except Exception as e:
        # This could be an error in os.remove or other unexpected issues
        app.logger.error(f"Generic exception during download for {url} (Format: {download_format}): {str(e)}")
        return jsonify({'success': False, 'error': 'An unexpected server error occurred during download.'}), 500
    finally:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                app.logger.info(f"Successfully deleted temporary file: {filepath}")
            except Exception as e:
                app.logger.error(f"Error deleting temporary file {filepath}: {str(e)}")

if __name__ == '__main__':
    # For production, use a proper WSGI server like Gunicorn or uWSGI
    app.run(debug=False) # debug=False is safer for anything potentially facing external users
