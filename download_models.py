"""Download a model explicitly; transcription itself remains offline."""
import argparse
from huggingface_hub import snapshot_download
from app import CACHE

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='下载本地中文转写模型（需要联网）')
    parser.add_argument('model', choices=['base', 'small', 'medium'], nargs='?', default='medium')
    args = parser.parse_args()
    snapshot_download(repo_id=f'Systran/faster-whisper-{args.model}', cache_dir=str(CACHE))
    print('模型已保存：', CACHE)
