import argparse
import json
import os
import pendulum
from retrying import retry
import requests
from notion_helper import NotionHelper
from covers import CoverStore
import utils

from douban_api import DOUBAN_API_HOST, DOUBAN_API_KEY, headers

from config import movie_properties_type_dict,book_properties_type_dict, TAG_ICON_URL, USER_ICON_URL
from utils import get_icon

rating = {
    1: "⭐️",
    2: "⭐️⭐️",
    3: "⭐️⭐️⭐️",
    4: "⭐️⭐️⭐️⭐️",
    5: "⭐️⭐️⭐️⭐️⭐️",
}
movie_status = {
    "mark": "想看",
    "doing": "在看",
    "done": "看过",
}
book_status = {
    "mark": "想读",
    "doing": "在读",
    "done": "读过",
}
@retry(stop_max_attempt_number=3, wait_fixed=5000)
def fetch_interests_page(url, params):
    response = requests.get(url, headers=headers, params=params, timeout=(10, 30))
    response.raise_for_status()
    interests = response.json().get("interests")
    if not isinstance(interests, list):
        raise ValueError("Douban response is missing the interests list")
    return interests


def fetch_subjects(user, type_, status):
    offset = 0
    page = 0
    url = f"https://{DOUBAN_API_HOST}/api/v2/user/{user}/interests"
    results = []
    while True:
        params = {
            "type": type_,
            "count": 50,
            "status": status,
            "start": offset,
            "apiKey": DOUBAN_API_KEY,
        }
        interests = fetch_interests_page(url, params)
        if not interests:
            break
        results.extend(interests)
        print(f"size = {len(results)}")
        page += 1
        offset = page * 50
    return results



def insert_movie():
    covers = CoverStore(notion_helper.client)
    actor_property_type = notion_helper.get_property_type(
        notion_helper.movie_database_id, "演员"
    )
    if actor_property_type not in ("rich_text", "multi_select"):
        raise ValueError("演员 property must be rich_text or multi_select")
    notion_movies = notion_helper.query_all(database_id=notion_helper.movie_database_id)
    notion_movie_dict = {}
    for i in notion_movies:
        movie = {}
        for key, value in i.get("properties").items():
            movie[key] = utils.get_property_value(value)
        notion_movie_dict[movie.get("豆瓣链接")] = {
            "短评": movie.get("短评"),
            "状态": movie.get("状态"),
            "日期": movie.get("日期"),
            "评分": movie.get("评分"),
            "page_id": i.get("id")
        }
    print(f"notion {len(notion_movie_dict)}")
    results = []
    for i in movie_status.keys():
        results.extend(fetch_subjects(douban_name, "movie", i))
    for result in results:
        movie = {}
        subject = result.get("subject")
        movie["电影名"] = subject.get("title")
        create_time = result.get("create_time")
        create_time = pendulum.parse(create_time,tz=utils.tz)
        #时间上传到Notion会丢掉秒的信息，这里直接将秒设置为0
        create_time = create_time.replace(second=0)
        movie["日期"] = create_time.int_timestamp
        movie["豆瓣链接"] = subject.get("url")
        movie["状态"] = movie_status.get(result.get("status"))
        if result.get("rating"):
            movie["评分"] = rating.get(result.get("rating").get("value"))
        if result.get("comment"):
            movie["短评"] = result.get("comment")
        if notion_movie_dict.get(movie.get("豆瓣链接")):
            notion_movive = notion_movie_dict.get(movie.get("豆瓣链接"))
            if (
                notion_movive.get("日期") != movie.get("日期")
                or notion_movive.get("短评") != movie.get("短评")
                or notion_movive.get("状态") != movie.get("状态")
                or notion_movive.get("评分") != movie.get("评分")
            ):
                properties = utils.get_properties(movie, movie_properties_type_dict)
                notion_helper.get_date_relation(properties,create_time)
                notion_helper.update_page(
                    page_id=notion_movive.get("page_id"),
                    properties=properties
            )

        else:
            print(f"插入{movie.get('电影名')}")
            cover = subject.get("pic").get("large")
            movie["封面"] = cover
            movie["类型"] = subject.get("type")
            if subject.get("genres"):
                movie["分类"] = [
                    notion_helper.get_relation_id(
                        x, notion_helper.category_database_id, TAG_ICON_URL
                    )
                    for x in subject.get("genres")
                ]
            if subject.get("actors"):
                l = []
                actors = subject.get("actors")[0:100]
                for actor in actors:
                    if actor.get("name"):
                        if "/" in actor.get("name"):
                            l.extend(actor.get("name").split("/"))
                        else:
                            l.append(actor.get("name"))  
                movie["演员"] = l
            if subject.get("directors"):
                movie["导演"] = [
                    notion_helper.get_relation_id(
                        x.get("name"), notion_helper.director_database_id, USER_ICON_URL
                    )
                    for x in subject.get("directors")[0:100]
                ]
            properties = utils.get_properties(movie, movie_properties_type_dict)
            if "演员" in movie:
                properties["演员"] = utils.get_actor_property(movie["演员"], actor_property_type)
            notion_helper.get_date_relation(properties,create_time)
            parent = {
                "database_id": notion_helper.movie_database_id,
                "type": "database_id",
            }
            properties["封面"], icon = covers.new_cover(cover, movie["豆瓣链接"])
            notion_helper.create_page(parent=parent, properties=properties, icon=icon)


def insert_book():
    covers = CoverStore(notion_helper.client)
    notion_books = notion_helper.query_all(database_id=notion_helper.book_database_id)
    notion_book_dict = {}
    for i in notion_books:
        book = {}
        for key, value in i.get("properties").items():
            book[key] = utils.get_property_value(value)
        notion_book_dict[book.get("豆瓣链接")] = {
            "短评": book.get("短评"),
            "状态": book.get("状态"),
            "日期": book.get("日期"),
            "评分": book.get("评分"),
            "page_id": i.get("id")
        }
    print(f"notion {len(notion_book_dict)}")
    results = []
    for i in book_status.keys():
        results.extend(fetch_subjects(douban_name, "book", i))
    for result in results:
        book = {}
        subject = result.get("subject")
        book["书名"] = subject.get("title")
        create_time = result.get("create_time")
        create_time = pendulum.parse(create_time,tz=utils.tz)
        #时间上传到Notion会丢掉秒的信息，这里直接将秒设置为0
        create_time = create_time.replace(second=0)
        book["日期"] = create_time.int_timestamp
        book["豆瓣链接"] = subject.get("url")
        book["状态"] = book_status.get(result.get("status"))
        if result.get("rating"):
            book["评分"] = rating.get(result.get("rating").get("value"))
        if result.get("comment"):
            book["短评"] = result.get("comment")
        if notion_book_dict.get(book.get("豆瓣链接")):
            notion_movive = notion_book_dict.get(book.get("豆瓣链接"))
            if (
                notion_movive.get("日期") != book.get("日期")
                or notion_movive.get("短评") != book.get("短评")
                or notion_movive.get("状态") != book.get("状态")
                or notion_movive.get("评分") != book.get("评分")
            ):
                properties = utils.get_properties(book, book_properties_type_dict)
                notion_helper.get_date_relation(properties,create_time)
                notion_helper.update_page(
                    page_id=notion_movive.get("page_id"),
                    properties=properties
            )

        else:
            print(f"插入{book.get('书名')}")
            cover = subject.get("pic").get("large")
            book["封面"] = cover
            book["简介"] = subject.get("intro")
            press = []
            for i in subject.get("press"):
                press.extend(i.split(","))
            book["出版社"] = press
            book["类型"] = subject.get("type")
            if result.get("tags"):
                book["分类"] = [
                    notion_helper.get_relation_id(
                        x, notion_helper.category_database_id, TAG_ICON_URL
                    )
                    for x in result.get("tags")
                ]
            if subject.get("author"):
                book["作者"] = [
                    notion_helper.get_relation_id(
                        x, notion_helper.author_database_id, USER_ICON_URL
                    )
                    for x in subject.get("author")[0:100]
                ]
            properties = utils.get_properties(book, book_properties_type_dict)
            notion_helper.get_date_relation(properties,create_time)
            parent = {
                "database_id": notion_helper.book_database_id,
                "type": "database_id",
            }
            properties["封面"], icon = covers.new_cover(cover, book["豆瓣链接"])
            notion_helper.create_page(parent=parent, properties=properties, icon=icon)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("type")
    options = parser.parse_args()
    type = options.type
    is_movie = True if type=="movie" else False
    notion_helper = NotionHelper(type)
    douban_name = os.getenv("DOUBAN_NAME", None)
    if is_movie:
        insert_movie()
    else:
        insert_book()
