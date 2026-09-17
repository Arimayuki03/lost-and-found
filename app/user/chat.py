import traceback
from datetime import datetime, timezone
from flask import request, jsonify, current_app, session
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from flask_socketio import emit, join_room, leave_room, disconnect
from sqlalchemy import text, or_, func, case
from app import db, socketio
from app.models import ChatMessage, User
from . import user
from functools import wraps


# 自定义Socket.IO认证装饰器，从请求中获取token并验证
def socketio_jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            # 尝试从会话中获取用户ID
            if session.get('user_id'):
                # 超管令牌不是用户身份，不允许参与用户聊天
                if session.get('role') == 'super_admin':
                    return emit('error', {'error': '无效的认证令牌'})
                # 如果会话中已存在用户ID，则使用它
                return f(*args, **kwargs)

            # 尝试从事件数据中获取token
            if args and isinstance(args[0], dict):
                # 首先尝试从authorization字段获取
                auth = args[0].get('authorization')
                if auth and auth.startswith('Bearer '):
                    token = auth.replace('Bearer ', '')
                else:
                    # 然后尝试从token字段获取
                    token = args[0].get('token')

                if token:
                    try:
                        # 验证并解码token
                        decoded_token = decode_token(token)
                        # 仅接受 access token；超管令牌不是用户身份
                        if decoded_token.get('type') != 'access' or decoded_token.get('role') == 'super_admin':
                            return emit('error', {'error': '无效的认证令牌'})
                        user_id = decoded_token['sub']  # JWT的subject字段
                        # 将用户ID存储在会话中
                        session['user_id'] = user_id
                        session['role'] = decoded_token.get('role')
                        # 修改args[0]以传递用户ID
                        args[0]['user_id'] = user_id
                        return f(*args, **kwargs)
                    except Exception as token_error:
                        current_app.logger.error(f"Token验证失败: {str(token_error)}")
                        return emit('error', {'error': '无效的认证令牌'})

            # 尝试从请求参数中获取token
            token = request.args.get('token')
            if token:
                try:
                    # 验证并解码token
                    decoded_token = decode_token(token)
                    # 仅接受 access token；超管令牌不是用户身份
                    if decoded_token.get('type') != 'access' or decoded_token.get('role') == 'super_admin':
                        return emit('error', {'error': '无效的认证令牌'})
                    user_id = decoded_token['sub']
                    # 将用户ID存储在会话中
                    session['user_id'] = user_id
                    session['role'] = decoded_token.get('role')
                    return f(*args, **kwargs)
                except Exception as token_error:
                    current_app.logger.error(f"Token验证失败: {str(token_error)}")
                    return emit('error', {'error': '无效的认证令牌'})

            # 如果没有找到有效的token
            return emit('error', {'error': '需要认证', 'code': 401})
        except Exception as e:
            current_app.logger.error(f"Socket.IO认证错误: {str(e)}")
            current_app.logger.error(traceback.format_exc())
            return emit('error', {'error': '认证失败', 'code': 401})

    return decorated


# 处理连接事件
@socketio.on('connect')
def handle_connect():
    try:
        # 从URL参数中获取token
        token = request.args.get('token')
        if token:
            try:
                # 验证并解码token
                decoded_token = decode_token(token)
                # 仅接受 access token；超管令牌不是用户身份
                if decoded_token.get('type') != 'access' or decoded_token.get('role') == 'super_admin':
                    raise ValueError('无效的认证令牌')
                user_id = decoded_token['sub']
                # 将用户ID存储在会话中
                session['user_id'] = user_id
                session['role'] = decoded_token.get('role')
                current_app.logger.info(f"用户 {user_id} 已连接")
                return True
            except Exception as token_error:
                current_app.logger.error(f"连接时Token验证失败: {str(token_error)}")
                # 允许连接，但不存储用户ID
                return True
        # 允许未认证连接，后续事件处理时再验证
        return True
    except Exception as e:
        current_app.logger.error(f"处理连接事件时出错: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return True  # 仍然允许连接


# 处理断开连接事件
@socketio.on('disconnect')
def handle_disconnect():
    try:
        user_id = session.get('user_id')
        if user_id:
            current_app.logger.info(f"用户 {user_id} 已断开连接")
            # 可以选择清除会话数据
            session.pop('user_id', None)
    except Exception as e:
        current_app.logger.error(f"处理断开连接事件时出错: {str(e)}")
        current_app.logger.error(traceback.format_exc())


# authenticate事件处理函数
@socketio.on('authenticate')
def handle_authenticate(data):
    try:
        # 首先尝试从authorization字段获取
        auth = data.get('authorization')
        if auth and auth.startswith('Bearer '):
            token = auth.replace('Bearer ', '')
        else:
            # 然后尝试从token字段获取
            token = data.get('token')

        if not token:
            return emit('authenticate_result', {'success': False, 'error': '认证令牌不能为空'})

        try:
            # 验证并解码token
            decoded_token = decode_token(token)
            # 仅接受 access token；超管令牌不是用户身份
            if decoded_token.get('type') != 'access' or decoded_token.get('role') == 'super_admin':
                return emit('authenticate_result', {'success': False, 'error': '无效的认证令牌'})
            user_id = decoded_token['sub']

            # 将用户ID存储在会话中
            session['user_id'] = user_id
            session['role'] = decoded_token.get('role')

            # 加入个人房间：私聊消息同时推给接收者的 user:<id> 房间，
            # 接收者不在对应 chat 房间（如停留在首页）时也能收到实时推送/未读角标
            join_room(f"user:{user_id}")

            # 返回认证成功响应
            return emit('authenticate_result', {'success': True, 'user_id': user_id})
        except Exception as token_error:
            current_app.logger.error(f"令牌验证失败: {str(token_error)}")
            return emit('authenticate_result', {'success': False, 'error': '无效的认证令牌'})
    except Exception as e:
        current_app.logger.error(f"认证处理错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return emit('authenticate_result', {'success': False, 'error': '认证处理失败'})


# 加入私聊房间请求
@socketio.on('join_private_chat')
@socketio_jwt_required
def on_join_private_chat(data):
    try:
        # 身份一律以认证时写入 session 的值为准，不信任事件数据
        user_id = session.get('user_id')
        if not user_id:
            return emit('join_private_chat_result', {'success': False, 'error': '未认证用户'})

        room = data.get('room')
        if not room:
            return emit('join_private_chat_result', {'success': False, 'error': '房间名不能为空'})

        # 检查房间名格式是否正确(chat:x-y)
        if not isinstance(room, str) or not room.startswith('chat:'):
            return emit('join_private_chat_result', {'success': False, 'error': '无效的房间名格式'})

        # 验证用户有权限加入此房间
        try:
            # 解析房间名中的用户ID
            room_parts = room.split(':')[1].split('-')
            if len(room_parts) != 2:
                return emit('join_private_chat_result', {'success': False, 'error': '无效的房间名格式'})

            user_id1 = int(room_parts[0])
            user_id2 = int(room_parts[1])

            # 验证当前用户是否是房间成员之一
            if int(user_id) != user_id1 and int(user_id) != user_id2:
                return emit('join_private_chat_result', {'success': False, 'error': '无权加入此房间'})

            # 记录另一个用户ID
            target_id = user_id2 if int(user_id) == user_id1 else user_id1

            # 加入房间
            join_room(room)

            # 发送成功消息给当前用户
            emit('join_private_chat_result', {
                'success': True,
                'room_name': room,
                'user_id': user_id,
                'target_id': target_id
            })

            # 通知房间内其他用户
            emit('user_status_change', {
                'user_id': user_id,
                'status': 'online',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, room=room, include_self=False)

            current_app.logger.info(f"用户 {user_id} 已成功加入私聊房间 {room}")

        except ValueError:
            return emit('join_private_chat_result', {'success': False, 'error': '房间名格式错误'})

    except Exception as e:
        current_app.logger.error(f"加入私聊房间错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return emit('join_private_chat_result', {'success': False, 'error': '加入私聊房间失败'})


# 处理离开私聊房间请求
@socketio.on('leave_private_chat')
@socketio_jwt_required
def on_leave_private_chat(data):
    try:
        # 身份一律以认证时写入 session 的值为准，不信任事件数据
        user_id = session.get('user_id')
        if not user_id:
            return emit('error', {'error': '未认证用户'})

        room = data.get('room') or data.get('room_name')
        if not room:
            return emit('error', {'error': '房间名不能为空'})

        # 只允许离开自己所属的私聊房间，避免向任意房间广播伪造的离线状态
        try:
            room_parts = room.split(':')[1].split('-')
            is_member = (len(room_parts) == 2
                         and int(user_id) in (int(room_parts[0]), int(room_parts[1])))
        except (IndexError, ValueError):
            is_member = False
        if not is_member:
            return emit('error', {'error': '无权操作此房间'})

        # 离开房间
        leave_room(room)

        # 通知房间内其他用户
        emit('user_status_change', {
            'user_id': user_id,
            'status': 'offline',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, room=room)
        disconnect()
        current_app.logger.info(f"用户 {user_id} 已离开私聊房间 {room}")
        return emit('leave_result', {'success': True, 'room': room})

    except Exception as e:
        current_app.logger.error(f"离开私聊房间错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return emit('error', {'error': '离开私聊房间失败'})


# 处理发送私聊消息请求
@socketio.on('send_private_message')
@socketio_jwt_required
def handle_send_private_message(data):
    try:
        # 身份一律以认证时写入 session 的值为准，不信任事件数据
        sender_id = session.get('user_id')
        if not sender_id:
            return emit('error', {'error': '未认证用户', 'originEvent': 'send_private_message'})

        receiver_id = data.get('receiver_id')
        message = data.get('message')

        if not receiver_id or not message:
            return emit('error', {'error': '接收者ID和消息内容不能为空', 'originEvent': 'send_private_message'})

        # 验证接收者是否存在
        receiver = User.query.get(receiver_id)
        if not receiver:
            return emit('error', {'error': '接收者不存在', 'originEvent': 'send_private_message'})

        # 验证消息长度
        if len(message) > 500:
            return emit('error', {'error': '消息长度不能超过500个字符', 'originEvent': 'send_private_message'})

        # 房间名以服务端按收发双方推导为准，不信任客户端传入，防止向任意房间注入消息
        try:
            room_ids = sorted([int(str(sender_id)), int(receiver_id)])
        except (TypeError, ValueError):
            return emit('error', {'error': '无效的用户ID', 'originEvent': 'send_private_message'})
        room_name = f"chat:{room_ids[0]}-{room_ids[1]}"

        # 创建消息记录
        chat_message = ChatMessage(
            sender_id=sender_id,
            receiver_id=receiver_id,
            message=message,
            is_read=False
        )
        db.session.add(chat_message)
        db.session.commit()

        # 准备消息数据
        message_data = chat_message.to_dict()
        # 添加房间名
        message_data['room_name'] = room_name

        # 在私聊房间中发送消息
        emit('receive_private_message', message_data, room=room_name)
        # 同时推给接收者的个人房间（接收者不在 chat 房间时也能收到；前端按消息 id 去重）
        emit('receive_private_message', message_data, room=f"user:{receiver_id}")

        # 返回成功消息给发送者
        emit('message_sent', {
            'success': True,
            'message_id': chat_message.id,
            'room_name': room_name,
            'temp_id': data.get('message_id')  # 返回临时ID以便前端匹配
        })

        current_app.logger.info(f"用户 {sender_id} 向用户 {receiver_id} 发送了私聊消息 ID:{chat_message.id}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"发送私聊消息错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return emit('error', {'error': '发送私聊消息失败', 'originEvent': 'send_private_message'})


# 处理私聊消息已读通知
@socketio.on('notify_message_read_private')
@socketio_jwt_required
def handle_private_message_read(data):
    try:
        # 身份一律以认证时写入 session 的值为准，不信任事件数据
        receiver_id = session.get('user_id')
        if not receiver_id:
            return emit('error', {'error': '未认证用户', 'originEvent': 'notify_message_read_private'})

        message_id = data.get('message_id')

        if not message_id:
            return emit('error', {'error': '消息ID不能为空', 'originEvent': 'notify_message_read_private'})

        # 验证消息是否存在
        message = ChatMessage.query.get(message_id)
        if not message:
            return emit('error', {'error': '消息不存在', 'originEvent': 'notify_message_read_private'})

        # 验证接收者身份
        if str(message.receiver_id) != str(receiver_id):
            return emit('error', {'error': '无权限标记此消息', 'originEvent': 'notify_message_read_private'})

        # 房间名与发送者以消息记录为准，不信任客户端传入
        room_ids = sorted([int(message.sender_id), int(message.receiver_id)])
        room = f"chat:{room_ids[0]}-{room_ids[1]}"

        # 更新消息状态为已读
        message.is_read = True
        db.session.execute(text("UPDATE chat_message SET read_at = CURRENT_TIMESTAMP WHERE id = :id"),
                           {"id": message_id})
        db.session.commit()

        # 向私聊房间发送消息已读通知
        emit('private_message_read', {
            'message_id': message_id,
            'receiver_id': receiver_id,
            'sender_id': message.sender_id,
            'room_name': room,
            'read_at': datetime.now(timezone.utc).isoformat()
        }, room=room)

        current_app.logger.info(f"已通知用户 {message.sender_id} 消息 {message_id} 已被用户 {receiver_id} 阅读")
    except Exception as e:
        current_app.logger.error(f"处理私聊消息已读通知错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        emit('error', {'error': '处理私聊消息已读通知失败', 'originEvent': 'notify_message_read_private'})


# 添加HTTP端点用于发送消息
@user.route('/chat/message', methods=['POST'])
@jwt_required()
def send_message():
    try:
        sender_id = get_jwt_identity()
        data = request.get_json(silent=True)

        if not data:
            return jsonify({"error": "无效的请求数据"}), 400

        receiver_id = data.get('receiver_id')
        message = data.get('message')

        if not receiver_id or not message:
            return jsonify({"error": "接收者ID和消息内容不能为空"}), 400

        # 类型防护：非字符串 message 会在 len() 处抛 TypeError；
        # 非数字 receiver_id 会在 User.query.get() 处抛异常落入 500
        try:
            receiver_id = int(receiver_id)
        except (TypeError, ValueError):
            return jsonify({"error": "接收者ID无效"}), 400
        if not isinstance(message, str):
            return jsonify({"error": "消息内容需为字符串"}), 400

        # 验证接收者是否存在
        receiver = User.query.get(receiver_id)
        if not receiver:
            return jsonify({"error": "接收者不存在"}), 404

        # 验证消息长度
        if len(message) > 500:
            return jsonify({"error": "消息长度不能超过500个字符"}), 400

        chat_message = ChatMessage(
            sender_id=sender_id,
            receiver_id=receiver_id,
            message=message,
            is_read=False
        )
        db.session.add(chat_message)
        db.session.commit()

        # 创建私聊房间名称
        user_ids = sorted([int(sender_id), int(receiver_id)])
        room_name = f"chat:{user_ids[0]}-{user_ids[1]}"

        # 通过Socket.IO发送实时通知
        try:
            socketio.emit('receive_private_message', {
                **chat_message.to_dict(),
                'room_name': room_name
            }, room=room_name)
            # 同时推给接收者的个人房间（接收者不在 chat 房间时也能收到；前端按消息 id 去重）
            socketio.emit('receive_private_message', {
                **chat_message.to_dict(),
                'room_name': room_name
            }, room=f"user:{int(receiver_id)}")
        except Exception as socket_error:
            current_app.logger.error(f"Socket通知发送失败: {str(socket_error)}")
            # 继续执行，不影响HTTP响应

        return jsonify({
            "success": True,
            "message": "消息发送成功",
            "message_id": chat_message.id,
            "timestamp": chat_message.timestamp.isoformat() if chat_message.timestamp else None
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"HTTP发送消息错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        # 不把内部异常原文回显给客户端（SQLAlchemy 异常文本包含 SQL 与绑定参数）
        return jsonify({"error": "发送消息失败"}), 500


# 消息历史
@user.route('/chat/history/<int:receiver_id>', methods=['GET'])
@jwt_required()
def get_chat_history(receiver_id):
    try:
        sender_id = get_jwt_identity()

        # 验证接收者是否存在
        receiver = User.query.get(receiver_id)
        if not receiver:
            return jsonify({"error": "接收者不存在"}), 404

        # 获取偏移量和限制（限制单次拉取量，防止一次性导出整段会话）
        offset = max(request.args.get('offset', 0, type=int) or 0, 0)
        limit = min(max(request.args.get('limit', 20, type=int) or 20, 1), 100)

        # 查询最新消息
        messages_query = ChatMessage.query.filter(
            ((ChatMessage.sender_id == sender_id) & (ChatMessage.receiver_id == receiver_id)) |
            ((ChatMessage.sender_id == receiver_id) & (ChatMessage.receiver_id == sender_id))
        ).order_by(ChatMessage.timestamp.desc()).offset(offset).limit(limit)

        # 返回消息数据
        return jsonify({
            "messages": [message.to_dict() for message in messages_query],
            "offset": offset,
            "limit": limit
        })
    except Exception as e:
        current_app.logger.error(f"获取聊天历史错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": "获取聊天历史失败"}), 500


# 添加标记消息为已读的功能
@user.route('/chat/mark/<int:message_id>', methods=['POST'])
@jwt_required()
def mark_message_read(message_id):
    try:
        user_id = get_jwt_identity()

        message = ChatMessage.query.get(message_id)
        if not message:
            return jsonify({"error": "消息不存在"}), 404

        # 确保只有接收者可以标记消息为已读
        if int(message.receiver_id) != int(user_id):
            return jsonify({"error": "无权限标记此消息"}), 403

        message.is_read = True
        # 使用 text() 函数包装 SQL 语句
        db.session.execute(text("UPDATE chat_message SET read_at = CURRENT_TIMESTAMP WHERE id = :id"),
                           {"id": message_id})
        db.session.commit()

        return jsonify({"success": True, "message": "消息已标记为已读"}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"标记消息已读错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": "标记消息失败"}), 500


# 将某个会话中"发给我的全部未读"一次性标记已读。
# 修复：聊天页原先只标记已加载的最近一页（20条），历史里的旧未读永远清不掉，
# 导致从聊天列表点进会话查看后退出，红点依然存在。
@user.route('/chat/read/<int:partner_id>', methods=['POST'])
@jwt_required()
def mark_conversation_read(partner_id):
    try:
        user_id = get_jwt_identity()

        unread_msgs = ChatMessage.query.filter(
            ChatMessage.sender_id == partner_id,
            ChatMessage.receiver_id == user_id,
            ChatMessage.is_read == False
        ).all()
        if not unread_msgs:
            return jsonify({"success": True, "marked": 0}), 200

        msg_ids = [m.id for m in unread_msgs]
        db.session.query(ChatMessage).filter(
            ChatMessage.id.in_(msg_ids)
        ).update({ChatMessage.is_read: True, ChatMessage.read_at: func.now()},
                 synchronize_session=False)
        db.session.commit()

        # 逐条向私聊房间推送已读回执（复用单条已读的载荷结构），
        # 让对方界面上的"未读/已读"状态实时刷新
        try:
            room_ids = sorted([int(user_id), int(partner_id)])
            room = f"chat:{room_ids[0]}-{room_ids[1]}"
            now_iso = datetime.now(timezone.utc).isoformat()
            for mid in msg_ids:
                socketio.emit('private_message_read', {
                    'message_id': mid,
                    'receiver_id': user_id,
                    'sender_id': partner_id,
                    'room_name': room,
                    'read_at': now_iso
                }, room=room)
        except Exception as socket_error:
            # 回执推送失败不影响已读结果（DB 已提交），仅记日志
            current_app.logger.error(f"批量已读回执推送失败: {str(socket_error)}")

        return jsonify({"success": True, "marked": len(msg_ids)}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"会话批量标记已读错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": "标记已读失败"}), 500


# 获取未读消息数量
@user.route('/chat/unread-count', methods=['GET'])
@jwt_required()
def get_unread_count():
    try:
        user_id = get_jwt_identity()

        # 获取所有发送给当前用户且未读的消息数量
        unread_count = ChatMessage.query.filter_by(
            receiver_id=user_id,
            is_read=False
        ).count()

        # 按发送者分组的未读消息数量
        unread_by_sender = db.session.query(
            ChatMessage.sender_id,
            db.func.count(ChatMessage.id).label('count')
        ).filter_by(
            receiver_id=user_id,
            is_read=False
        ).group_by(ChatMessage.sender_id).all()

        sender_counts = {str(sender_id): count for sender_id, count in unread_by_sender}

        return jsonify({
            "total_unread": unread_count,
            "unread_by_sender": sender_counts
        }), 200
    except Exception as e:
        current_app.logger.error(f"获取未读消息数量错误: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": "获取未读消息数量失败"}), 500


# 查询当前用户与哪些用户聊过天
@user.route('/chat/contacts', methods=['GET'])
@jwt_required()
def get_chat_contacts():
    try:
        current_user_id = get_jwt_identity()

        # 查询与当前用户有过消息往来的用户ID
        sent_contacts = db.session.query(ChatMessage.receiver_id).filter_by(sender_id=current_user_id).distinct()
        received_contacts = db.session.query(ChatMessage.sender_id).filter_by(receiver_id=current_user_id).distinct()

        # 合并并去重
        contacts = set(contact[0] for contact in sent_contacts.union(received_contacts))

        # 查询用户信息
        users = User.query.filter(User.id.in_(contacts)).all()

        # 批量取每个会话的最后一条消息与未读数，避免逐联系人查询（N+1）
        last_id_rows = db.session.query(func.max(ChatMessage.id)).filter(
            or_(ChatMessage.sender_id == current_user_id, ChatMessage.receiver_id == current_user_id)
        ).group_by(
            case((ChatMessage.sender_id == current_user_id, ChatMessage.receiver_id), else_=ChatMessage.sender_id)
        ).all()
        last_msgs_by_partner = {}
        if last_id_rows:
            # .all() 返回的是 Row 元组，直接传给 in_ 会被当作绑定参数报错，必须取第一列展平
            last_ids = [row[0] for row in last_id_rows]
            for msg in ChatMessage.query.filter(ChatMessage.id.in_(last_ids)).all():
                partner_id = msg.receiver_id if str(msg.sender_id) == str(current_user_id) else msg.sender_id
                last_msgs_by_partner[partner_id] = msg
        unread_rows = db.session.query(
            ChatMessage.sender_id, func.count(ChatMessage.id)
        ).filter_by(receiver_id=current_user_id, is_read=False).group_by(ChatMessage.sender_id).all()
        unread_by_partner = {sender_id: count for sender_id, count in unread_rows}

        # 将用户信息转换为字典列表（附带最后一条消息与未读数，供会话列表展示摘要/时间/角标）
        users_list = []
        for contact_user in users:
            last_msg = last_msgs_by_partner.get(contact_user.id)
            unread = unread_by_partner.get(contact_user.id, 0)
            users_list.append({
                "id": contact_user.id,
                "name": contact_user.name,
                "avatar_url": contact_user.avatar_url,
                "last_message": last_msg.message if last_msg else None,
                "last_message_time": last_msg.timestamp.isoformat() if last_msg and last_msg.timestamp else None,
                "last_message_sender_id": last_msg.sender_id if last_msg else None,
                "unread_count": unread,
            })

        # 检查是否有联系人
        if not users_list:
            return jsonify({"message": "没有找到聊天联系人"}), 200

        return jsonify(users_list), 200
    except Exception as e:
        current_app.logger.error(f"获取聊天联系人错误: {str(e)}")
        return jsonify({"error": "获取聊天联系人失败"}), 500
