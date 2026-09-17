from app.utils.decorators import admin_required
from . import admin
from flask import request, jsonify, current_app
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import LostItem, FoundItem, ItemMatch
from sqlalchemy import extract, func
import datetime


# 统计拾物和失物数量接口
@admin.route('/stats', methods=['GET'])
@admin_required
def get_stats():
    try:
        # 统计失物和拾物的总数
        lost_total = LostItem.query.count()
        found_total = FoundItem.query.count()

        # 统计未审核的失物和拾物数量
        unreviewed_lost_items = LostItem.query.filter_by(is_under_review=True).count()
        unreviewed_found_items = FoundItem.query.filter_by(is_under_review=True).count()

        # 统计已匹配的物品数量
        matched_items = ItemMatch.query.count()

        # 计算匹配成功率
        match_success_rate = 0
        if (lost_total + found_total) > 0:
            match_success_rate = round((matched_items * 2) / (lost_total + found_total) * 100, 2)

        current_app.logger.info("成功获取失物和拾物的统计数据")
        return jsonify({
            "lostTotal": lost_total,
            "foundTotal": found_total,
            "unreviewedLostItems": unreviewed_lost_items,
            "unreviewedFoundItems": unreviewed_found_items,
            "matchedItems": matched_items,
            "matchSuccessRate": match_success_rate
        }), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"获取统计数据时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 获取时间范围的日期限制
def get_time_range_filter(time_range, time_field):
    now = datetime.datetime.now()

    if time_range == '7days':
        start_date = now - datetime.timedelta(days=7)
        return time_field >= start_date
    elif time_range == '30days':
        start_date = now - datetime.timedelta(days=30)
        return time_field >= start_date
    elif time_range == '12months':
        start_date = now - datetime.timedelta(days=365)
        return time_field >= start_date
    else:
        return True


# 失物统计接口
@admin.route('/lost-items/stats', methods=['GET'])
@admin_required
def get_lost_items_stats():
    try:
        # 获取查询参数
        n = request.args.get('n', default=10, type=int)
        time_range = request.args.get('time_range', default='all')

        # 构建时间范围过滤条件
        time_filter = get_time_range_filter(time_range, LostItem.lost_time)

        # 按类别统计失物数量
        category_result = db.session.query(
            LostItem.category,
            func.count(LostItem.id)
        ).filter(time_filter).group_by(LostItem.category).order_by(func.count(LostItem.id).desc()).limit(n).all()

        # 转换为前端期望的格式
        category_stats = [{"name": category, "value": count} for category, count in category_result]

        # 按时间统计失物数量（只保留默认的月视图，取决于前端实际需要）
        # 默认按月统计
        time_result = db.session.query(
            extract('year', LostItem.lost_time).label('year'),
            extract('month', LostItem.lost_time).label('month'),
            func.count(LostItem.id).label('count')
        ).filter(time_filter).group_by('year', 'month').order_by('year', 'month').all()

        # 创建过去12个月的月份列表
        month_stats = []
        for i in range(11, -1, -1):
            month_date = datetime.datetime.now() - datetime.timedelta(days=i * 30)
            month_str = f"{month_date.year}-{month_date.month:02d}"
            month_stats.append({"month": month_str, "count": 0})

        # 填充统计数据
        for year, month, count in time_result:
            month_str = f"{int(year)}-{int(month):02d}"
            for item in month_stats:
                if item["month"] == month_str:
                    item["count"] = count
                    break

        time_stats = month_stats

        # 按地点统计失物数量
        location_result = db.session.query(
            LostItem.location,
            func.count(LostItem.id)
        ).filter(time_filter).group_by(LostItem.location).order_by(func.count(LostItem.id).desc()).limit(n).all()

        # 转换为前端期望的格式
        location_stats = [{"location": location, "count": count} for location, count in location_result]

        current_app.logger.info("成功获取失物统计数据")
        return jsonify({
            "categoryStats": category_stats,
            "timeStats": time_stats,
            "locationStats": location_stats
        }), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"获取失物统计数据时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 拾物统计接口
@admin.route('/found-items/stats', methods=['GET'])
@admin_required
def get_found_items_stats():
    try:
        # 获取查询参数
        n = request.args.get('n', default=10, type=int)
        time_range = request.args.get('time_range', default='all')

        # 构建时间范围过滤条件
        time_filter = get_time_range_filter(time_range, FoundItem.found_time)

        # 按类别统计拾物数量
        category_result = db.session.query(
            FoundItem.category,
            func.count(FoundItem.id)
        ).filter(time_filter).group_by(FoundItem.category).order_by(func.count(FoundItem.id).desc()).limit(n).all()

        # 转换为前端期望的格式
        category_stats = [{"name": category, "value": count} for category, count in category_result]

        # 只保留默认的月视图
        # 默认按月统计
        time_result = db.session.query(
            extract('year', FoundItem.found_time).label('year'),
            extract('month', FoundItem.found_time).label('month'),
            func.count(FoundItem.id).label('count')
        ).filter(time_filter).group_by('year', 'month').order_by('year', 'month').all()

        # 创建过去12个月的月份列表
        month_stats = []
        for i in range(11, -1, -1):
            month_date = datetime.datetime.now() - datetime.timedelta(days=i * 30)
            month_str = f"{month_date.year}-{month_date.month:02d}"
            month_stats.append({"month": month_str, "count": 0})

        # 填充统计数据
        for year, month, count in time_result:
            month_str = f"{int(year)}-{int(month):02d}"
            for item in month_stats:
                if item["month"] == month_str:
                    item["count"] = count
                    break

        time_stats = month_stats

        # 按地点统计拾物数量
        location_result = db.session.query(
            FoundItem.location,
            func.count(FoundItem.id)
        ).filter(time_filter).group_by(FoundItem.location).order_by(func.count(FoundItem.id).desc()).limit(n).all()

        # 转换为前端期望的格式
        location_stats = [{"location": location, "count": count} for location, count in location_result]

        current_app.logger.info("成功获取拾物统计数据")
        return jsonify({
            "categoryStats": category_stats,
            "timeStats": time_stats,
            "locationStats": location_stats
        }), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"获取拾物统计数据时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 匹配统计接口
@admin.route('/matching/stats', methods=['GET'])
@admin_required
def get_matching_stats():
    try:
        # 统计总数量
        lost_total = LostItem.query.count()
        found_total = FoundItem.query.count()
        # 统计已匹配数量
        matched_lost_count = db.session.query(ItemMatch.lost_item_id).distinct().count()
        matched_found_count = db.session.query(ItemMatch.found_item_id).distinct().count()
        # 计算未匹配数量
        unmatched_lost_count = lost_total - matched_lost_count
        unmatched_found_count = found_total - matched_found_count

        # 计算匹配成功率
        def calculate_match_rate(matched_count, total_count):
            return 0 if total_count == 0 else round(matched_count / total_count * 100, 2)

        lost_match_rate = calculate_match_rate(matched_lost_count, lost_total)
        found_match_rate = calculate_match_rate(matched_found_count, found_total)
        overall_match_rate = calculate_match_rate(
            matched_lost_count + matched_found_count,
            lost_total + found_total
        )
        # 封装匹配统计数据
        match_stats = {
            "matched": {
                "lost": matched_lost_count,
                "found": matched_found_count,
                "total": matched_lost_count + matched_found_count
            },
            "unmatched": {
                "lost": unmatched_lost_count,
                "found": unmatched_found_count,
                "total": unmatched_lost_count + unmatched_found_count
            },
            "matchRate": {
                "lost": lost_match_rate,
                "found": found_match_rate,
                "overall": overall_match_rate
            }
        }
        current_app.logger.info(f"成功获取匹配统计数据: {match_stats}")
        return jsonify(match_stats), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"获取匹配统计数据时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
