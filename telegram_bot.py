from youtube_transcript_api import YouTubeTranscriptApi

ytt_api = YouTubeTranscriptApi()
fetched = ytt_api.fetch("pXm_rAB6KN4")  # ← ဒီ video ID

transcript_list = []
for snippet in fetched:
    transcript_list.append({
        "text": snippet.text,
        "start": snippet.start,
        "duration": snippet.duration
    })
