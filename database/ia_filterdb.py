# This code has been modified by @Looteredev
# Please do not remove this credit
import logging
from struct import pack
import re
import base64
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME, USE_CAPTION_FILTER, MAX_B_TN
from utils import get_settings, save_group_settings
from fuzzywuzzy import process
from Script import script

# Set up logging
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _clean_display_file_name(file_name):
    """Clean common promotional prefixes for display without changing stored names."""
    if not file_name:
        return ""
    text = str(file_name)
    metadata = re.compile(
        r"(?i)\b(?:s\d+\s*e\d+|season\s*\d+|episode\s*\d+|\d{3,4}p|4k|8k|"
        r"hdr|hevc|x264|x265|hindi|english|tamil|telugu|malayalam|kannada|"
        r"dual\s*audio|multi\s*audio|20\d{2})\b"
    )
    while True:
        prefix = re.match(r"\s*[\[\(\{]([^\]\)\}]+)[\]\)\}]\s*[-_. ]*", text)
        if not prefix or metadata.search(prefix.group(1)):
            break
        text = text[prefix.end():]
    text = re.sub(r"^\s*@[\w.]+\s*[-_.:]*\s*", "", text)
    text = re.sub(
        r"(?i)^\s*[\w.-]*(?:team|group|channel|uploads?|releases?)\s*[-_.:]+\s*",
        "",
        text,
    )
    text = re.sub(r"[_\.+]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ._+-")
    return text or str(file_name)


def _season_sort_key(file_name):
    """Sort season packs first, then episode numbers naturally."""
    text = _clean_display_file_name(file_name).lower()
    combined_episode = re.search(r"\bs0*(\d+)\s*e0*(\d+)\b", text)
    season_match = re.search(r"\b(?:season|s)\s*0*(\d+)\b", text)
    episode_match = re.search(r"\b(?:episode|ep|e)\s*0*(\d+)\b", text)
    if combined_episode:
        season = int(combined_episode.group(1))
        episode = int(combined_episode.group(2))
        is_season_pack = 1
    else:
        season = int(season_match.group(1)) if season_match else 9999
        episode = int(episode_match.group(1)) if episode_match else 9999
        is_season_pack = 0 if season_match and not episode_match else 1
    return (is_season_pack, season, episode, text)


client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

@instance.register
class Media(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)

    class Meta:
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME


async def save_file(media):
    """Save file in database"""

    # TODO: Find better way to get same file_id for same media to avoid duplicates
    file_id, file_ref = unpack_new_file_id(media.file_id)
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
        )
    except ValidationError:
        logger.exception('Error occurred while saving file in database')
        return False, None
    else:
        try:
            await file.commit()
        except DuplicateKeyError:      
            logger.warning(
                f'{getattr(media, "file_name", "NO_FILE")} is already saved in database'
            )

            return False, file_id
        else:
            logger.info(f'{getattr(media, "file_name", "NO_FILE")} is saved to database')
            return True, file_id



async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0, filter=False):
    """For given query return (results, next_offset)"""
    banned_words = script.BLACKLIST
    if chat_id is not None:
        settings = await get_settings(int(chat_id))
        try:
            if settings['max_btn']:
                max_results = 10
            else:
                max_results = int(MAX_B_TN)
        except KeyError:
            await save_group_settings(int(chat_id), 'max_btn', False)
            settings = await get_settings(int(chat_id))
            if settings['max_btn']:
                max_results = 10
            else:
                max_results = int(MAX_B_TN)
    query = query.strip()
    #if filter:
        #better ?
        #query = query.replace(' ', r'(\s|\.|\+|\-|_)')
        #raw_pattern = r'(\s|_|\-|\.|\+)' + query + r'(\s|_|\-|\.|\+)'
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_]')
    
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return []

    if USE_CAPTION_FILTER:
        filter = {'$or': [{'file_name': regex}, {'caption': regex}]}
    else:
        filter = {'file_name': regex}

    if file_type:
        filter['file_type'] = file_type

    total_results = await Media.count_documents(filter)
    next_offset = offset + max_results

    if next_offset > total_results:
        next_offset = ''

    cursor = Media.find(filter)
    # Keep pagination bounded, then sort the display results for season-first browsing.
    cursor.sort('$natural', -1)
    cursor.skip(offset).limit(max_results)
    files = await cursor.to_list(length=max_results)
    for file in files:
        for banned_word in banned_words:
            pattern = re.compile(re.escape(banned_word), re.IGNORECASE)
            file['file_name'] = pattern.sub('', file['file_name']).strip()
        file['file_name'] = _clean_display_file_name(file.get('file_name'))

    files.sort(key=lambda file: _season_sort_key(file.get('file_name')))
    return files, next_offset, total_results

async def get_all_files():
    cursor = Media.find() 
    all_files = await cursor.to_list(length=10000)  
    return [file['file_name'] for file in all_files]

async def get_bad_files(query, file_type=None, filter=False):
    """For given query return (results, next_offset)"""
    query = query.strip()
    #if filter:
        #better ?
        #query = query.replace(' ', r'(\s|\.|\+|\-|_)')
        #raw_pattern = r'(\s|_|\-|\.|\+)' + query + r'(\s|_|\-|\.|\+)'
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_]')
    
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return []

    if USE_CAPTION_FILTER:
        filter = {'$or': [{'file_name': regex}, {'caption': regex}]}
    else:
        filter = {'file_name': regex}

    if file_type:
        filter['file_type'] = file_type

    total_results = await Media.count_documents(filter)

    cursor = Media.find(filter)
    # Sort by recent
    cursor.sort('$natural', -1)
    # Get list of files
    files = await cursor.to_list(length=total_results)
    for file in files:
        file['file_name'] = _clean_display_file_name(file.get('file_name'))
    files.sort(key=lambda file: _season_sort_key(file.get('file_name')))

    return files, total_results

async def get_file_details(query):
    try:
        banned_words = script.BLACKLIST
        filter = {'file_id': query}
        cursor = Media.find(filter)
        filedetails = await cursor.to_list(length=1)
        if filedetails:
            file = filedetails[0]
            original_file_name = getattr(file, 'file_name', '')
            modified_file_name = original_file_name
            for banned_word in banned_words:
                pattern = re.compile(re.escape(banned_word), re.IGNORECASE)
                modified_file_name = pattern.sub('', modified_file_name).strip()
            modified_file_name = _clean_display_file_name(modified_file_name)
            if not modified_file_name:
                modified_file_name = "DefaultFileName"
            setattr(file, 'file_name', modified_file_name)
        return filedetails
    except Exception as e:
        logging.error("An error occurred:", exc_info=True)
        return None

def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0

    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0

            r += bytes([i])

    return base64.urlsafe_b64encode(r).decode().rstrip("=")


def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")


def unpack_new_file_id(new_file_id):
    """Return file_id, file_ref"""
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
