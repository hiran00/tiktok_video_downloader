document.addEventListener('DOMContentLoaded', () => {
    const tiktokUrlInput = document.getElementById('tiktokUrl');
    const videoPreviewDiv = document.getElementById('videoPreview');
    const downloadStatusDiv = document.getElementById('downloadStatus');
    const loaderDiv = document.getElementById('loader');

    const downloadButtons = [
        document.getElementById('downloadMp4'),
        document.getElementById('downloadMp4NoWatermark'),
        document.getElementById('downloadMp3')
    ];

    let isFetchingDetails = false;
    let isDownloading = false;

    function showLoader() {
        if (loaderDiv) loaderDiv.style.display = 'block';
    }

    function hideLoader() {
        if (loaderDiv) loaderDiv.style.display = 'none';
    }

    function disableAllButtons(disabled = true) {
        downloadButtons.forEach(button => {
            if (button) button.disabled = disabled;
        });
        if (tiktokUrlInput) tiktokUrlInput.disabled = disabled; // Optionally disable input during critical operations
    }
    
    function setStatus(message, type = 'info') { // type can be 'info', 'success', 'error'
        downloadStatusDiv.innerHTML = `<p class="status-${type}">${message}</p>`;
    }

    function clearStatus() {
        downloadStatusDiv.innerHTML = '';
    }
    
    function clearPreview() {
        videoPreviewDiv.innerHTML = '';
    }

    function validateUrl(url) {
        if (!url) {
            clearPreview();
            clearStatus();
            disableAllButtons(true); // No URL, disable download buttons
            return false;
        }
        // Basic regex for TikTok/Douyin URLs - can be improved for more strictness
        const tiktokRegex = /^(https?:\/\/)?(www\.)?(tiktok\.com|douyin\.com)\/.+/;
        if (tiktokRegex.test(url)) {
            disableAllButtons(false); // Valid URL pattern, enable buttons (if not already processing)
            return true;
        } else {
            clearPreview();
            setStatus('Please paste a valid TikTok or Douyin URL.', 'error');
            disableAllButtons(true); // Invalid URL, disable download buttons
            return false;
        }
    }


    if (tiktokUrlInput) {
        tiktokUrlInput.addEventListener('paste', (event) => setTimeout(() => handleUrlInput(event.target.value), 0));
        tiktokUrlInput.addEventListener('input', (event) => handleUrlInput(event.target.value));
        // Initial validation for pre-filled URL (if any, though unlikely for this app)
        validateUrl(tiktokUrlInput.value);
        if (!tiktokUrlInput.value) { // Ensure buttons are disabled on load if input is empty
            disableAllButtons(true);
        }
    }

    function handleUrlInput(url) {
        if (!validateUrl(url)) {
            return;
        }
        if (isFetchingDetails) {
            setStatus('Already fetching video details. Please wait.', 'info');
            return;
        }
        clearPreview();
        clearStatus();
        setStatus('Fetching video details...', 'info');
        showLoader();
        fetchVideoDetails(url);
    }

    downloadButtons.forEach(button => {
        if (button) {
            button.addEventListener('click', () => {
                const format = button.id.replace('download', '').toLowerCase();
                let actualFormat = format;
                if (format === "mp4nowatermark") actualFormat = "mp4_no_watermark";
                else if (format === "mp3") actualFormat = "mp3";
                else actualFormat = "mp4";
                
                handleDownload(actualFormat);
            });
        }
    });

    function handleDownload(format) {
        const url = tiktokUrlInput.value;
        if (!validateUrl(url)) { // Re-validate before download
            return;
        }
        if (isDownloading) {
            setStatus('Another download is already in progress.', 'info');
            return;
        }
        setStatus('Preparing download... Please wait.', 'info');
        showLoader();
        disableAllButtons(true);
        isDownloading = true;
        triggerDownload(url, format);
    }

    function determineFilename(response, format) {
        const disposition = response.headers.get('content-disposition');
        if (disposition && disposition.includes('attachment')) {
            const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
            const matches = filenameRegex.exec(disposition);
            if (matches != null && matches[1]) {
                let filename = matches[1].replace(/['"]/g, '');
                try {
                    // Handles most cases like %20, %E2%80%93 etc.
                    filename = decodeURIComponent(filename); 
                } catch (e) {
                    // If decodeURIComponent fails (e.g. malformed URI), use the raw filename
                    console.warn('decodeURIComponent failed for filename:', filename, e);
                }
                // Check if backend might have sent filename*=UTF-8'' format
                // This is a simplified check. Proper parsing is more complex.
                const utf8FilenameMatch = /filename\*=UTF-8''([\w%.-]+)/i.exec(disposition);
                if (utf8FilenameMatch && utf8FilenameMatch[1]) {
                    try {
                        filename = decodeURIComponent(utf8FilenameMatch[1]);
                    } catch (e) {
                        console.warn('decodeURIComponent failed for UTF-8 filename:', utf8FilenameMatch[1], e);
                        // Fallback to the previously decoded/raw filename
                    }
                }
                return filename;
            }
        }
        // Fallback filename
        const videoTitle = videoPreviewDiv.querySelector('h3')?.textContent?.replace(/[<>:"/\\|?*]+/g, '_') || 'downloaded_video';
        const safeTitle = videoTitle.substring(0, 50); // Limit length
        const defaultName = `${safeTitle}.${format === 'mp3' ? 'mp3' : 'mp4'}`;
        console.warn(`Could not determine filename from Content-Disposition. Falling back to ${defaultName}. Header: ${disposition}`);
        return defaultName;
    }

    async function triggerDownload(url, format) {
        isDownloading = true; // Set flag
        try {
        try {
            const response = await fetch('/download_video', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: url, format: format }),
            });

            if (response.ok) {
                const contentType = response.headers.get("content-type");
                if (contentType && (contentType.includes("application/octet-stream") || contentType.includes("video/") || contentType.includes("audio/"))) {
                    const blob = await response.blob();
                    const objectUrl = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = objectUrl;
                    a.download = determineFilename(response, format); // Use the enhanced function
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(objectUrl);
                    setStatus('Download initiated successfully!', 'success');
                } else if (contentType && contentType.includes("application/json")) {
                    const errorData = await response.json();
                    setStatus(errorData.error || 'Download failed. Please try again.', 'error');
                } else {
                     setStatus('Download failed: Unexpected response from server.', 'error');
                }
            } else {
                try {
                    const errorData = await response.json();
                    setStatus(errorData.error || `Download failed (Status: ${response.status})`, 'error');
                } catch (e) {
                    setStatus(`Error: Download request failed (Status: ${response.status}). Please try again.`, 'error');
                }
            }
        } catch (error) {
            console.error('Download error:', error);
            setStatus('Download failed: An unexpected error occurred. Check console for details.', 'error');
        } finally {
            hideLoader();
            disableAllButtons(false); // Re-enable all buttons
            isDownloading = false; // Reset flag
            if (tiktokUrlInput && !tiktokUrlInput.value) { // If URL was cleared during download process
                disableAllButtons(true);
            }
        }
    }

    async function fetchVideoDetails(videoUrl) {
        isFetchingDetails = true;
        // showLoader(); // Already called by handleUrlInput
        // disableAllButtons(true); // Optionally disable buttons during fetch

        try {
            const response = await fetch('/fetch_video_info', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: videoUrl }),
            });
            
            clearPreview(); // Clear previous preview before showing new one or error

            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    const titleElement = document.createElement('h3');
                    titleElement.textContent = data.title || 'Video Title'; // Fallback title

                    const thumbnailElement = document.createElement('img');
                    thumbnailElement.src = data.thumbnail;
                    thumbnailElement.alt = data.title ? `Thumbnail for ${data.title}` : 'Video thumbnail';
                    // CSS will handle styling: thumbnailElement.style.maxWidth = '100%'; etc.

                    videoPreviewDiv.appendChild(titleElement);
                    videoPreviewDiv.appendChild(thumbnailElement);
                    clearStatus(); // Clear "Fetching..." message
                } else {
                    setStatus(data.error || 'Could not fetch video details.', 'error');
                }
            } else {
                let errorMsg = `Error: Could not connect to the server (Status: ${response.status}).`;
                try {
                    const errorData = await response.json(); // Try to parse backend error
                    errorMsg = errorData.error || errorMsg;
                } catch(e) { /* Ignore if error response is not JSON */ }
                setStatus(errorMsg, 'error');
            }
        } catch (error) {
            setStatus('An unexpected error occurred while fetching details. Please check your connection and try again.', 'error');
            console.error('Fetch details error:', error);
        } finally {
            hideLoader();
            isFetchingDetails = false;
            // Re-enable buttons if they were disabled specifically for fetch
            // disableAllButtons(false); 
            // Current logic: buttons are primarily disabled by URL validity or active download.
            // If URL is valid after fetch, buttons should remain enabled.
            validateUrl(tiktokUrlInput.value); // Re-validate to set button states correctly
        }
    }
});
