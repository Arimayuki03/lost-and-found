/*
 Navicat Premium Data Transfer

 Source Server         : bkxt202112020071
 Source Server Type    : MySQL
 Source Server Version : 80034
 Source Host           : localhost:3306
 Source Schema         : lost_and_found

 Target Server Type    : MySQL
 Target Server Version : 80034
 File Encoding         : 65001

 Date: 11/03/2025 01:04:30
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for alembic_version
-- ----------------------------
DROP TABLE IF EXISTS `alembic_version`;
CREATE TABLE `alembic_version`  (
  `version_num` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '版本号',
  PRIMARY KEY (`version_num`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '数据库版本管理表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for announcement
-- ----------------------------
DROP TABLE IF EXISTS `announcement`;
CREATE TABLE `announcement` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '公告ID',
  `title` varchar(200) NOT NULL COMMENT '公告标题',
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '公告内容',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='公告表';

-- ----------------------------
-- Table structure for carousel_image
-- ----------------------------
DROP TABLE IF EXISTS `carousel_image`;
CREATE TABLE `carousel_image` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '轮播图ID',
  `image_url` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '图片URL',
  `description` varchar(255) DEFAULT NULL COMMENT '描述',
  `order` int NOT NULL DEFAULT '0' COMMENT '显示顺序',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='轮播图表';

-- ----------------------------
-- Table structure for chat_message
-- ----------------------------
DROP TABLE IF EXISTS `chat_message`;
CREATE TABLE `chat_message`  (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '消息ID',
  `sender_id` int NOT NULL COMMENT '发送者ID',
  `receiver_id` int NOT NULL COMMENT '接收者ID',
  `message` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '消息内容',
  `timestamp` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发送时间',
  `is_read` tinyint(1) NULL DEFAULT 0 COMMENT '是否已读',
  `read_at` timestamp NULL DEFAULT NULL COMMENT '阅读时间',
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `sender_id`(`sender_id` ASC) USING BTREE,
  INDEX `receiver_id`(`receiver_id` ASC) USING BTREE,
  CONSTRAINT `chat_message_ibfk_1` FOREIGN KEY (`sender_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `chat_message_ibfk_2` FOREIGN KEY (`receiver_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB AUTO_INCREMENT = 1 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '聊天消息表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Table structure for feedback
-- ----------------------------
DROP TABLE IF EXISTS `feedback`;
CREATE TABLE `feedback` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '反馈ID',
  `user_id` int NOT NULL COMMENT '用户ID',
  `content` text NOT NULL COMMENT '反馈内容',
  `timestamp` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '提交时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `user_id` (`user_id`) USING BTREE,
  CONSTRAINT `feedback_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户反馈表';

-- ----------------------------
-- Table structure for found_item
-- ----------------------------
DROP TABLE IF EXISTS `found_item`;
CREATE TABLE `found_item` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '招领物品ID',
  `category` varchar(50) NOT NULL COMMENT '物品类别',
  `name` varchar(100) NOT NULL COMMENT '物品名称',
  `description` text COMMENT '详细描述',
  `found_time` datetime NOT NULL COMMENT '拾获时间',
  `location` varchar(200) NOT NULL COMMENT '拾取地点',
  `contact` varchar(50) NOT NULL COMMENT '联系方式',
  `image_url` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '图片URL',
  `user_id` int NOT NULL COMMENT '登记用户ID',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_completed` tinyint DEFAULT NULL COMMENT '是否完成',
  `is_under_review` tinyint NOT NULL COMMENT '是否审核',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_found_item_user_id` (`user_id`) USING BTREE,
  CONSTRAINT `found_item_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='招领表';

-- ----------------------------
-- Table structure for item_match
-- ----------------------------
DROP TABLE IF EXISTS `item_match`;
CREATE TABLE `item_match` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '匹配ID',
  `lost_item_id` int NOT NULL COMMENT '失物ID',
  `found_item_id` int NOT NULL COMMENT '招领物品ID',
  `similarity_score` float NOT NULL COMMENT '总相似度分数',
  `name_similarity` float NOT NULL COMMENT '名称相似度',
  `category_similarity` float NOT NULL COMMENT '类别相似度',
  `location_similarity` float NOT NULL COMMENT '地点相似度',
  `time_similarity` float NOT NULL COMMENT '时间相似度',
  `matched_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '匹配时间',
  `notified` tinyint(1) DEFAULT '0' COMMENT '是否已通知',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_lost_found` (`lost_item_id`,`found_item_id`),
  KEY `lost_item_id` (`lost_item_id`) USING BTREE,
  KEY `found_item_id` (`found_item_id`) USING BTREE,
  CONSTRAINT `item_match_ibfk_1` FOREIGN KEY (`lost_item_id`) REFERENCES `lost_item` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT `item_match_ibfk_2` FOREIGN KEY (`found_item_id`) REFERENCES `found_item` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='物品匹配表';

-- ----------------------------
-- Table structure for lost_item
-- ----------------------------
DROP TABLE IF EXISTS `lost_item`;
CREATE TABLE `lost_item` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '失物ID',
  `category` varchar(50) NOT NULL COMMENT '物品类别',
  `name` varchar(100) NOT NULL COMMENT '物品名称',
  `description` text COMMENT '详细描述',
  `lost_time` datetime NOT NULL COMMENT '遗失时间',
  `location` varchar(200) NOT NULL COMMENT '遗失地点',
  `contact` varchar(50) NOT NULL COMMENT '联系方式',
  `image_url` varchar(255) DEFAULT NULL,
  `user_id` int NOT NULL COMMENT '登记用户ID',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_completed` tinyint NOT NULL COMMENT '是否完成',
  `is_under_review` tinyint NOT NULL COMMENT '是否审核',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_lost_item_category` (`category`) USING BTREE,
  KEY `idx_lost_item_user_id` (`user_id`) USING BTREE,
  CONSTRAINT `lost_item_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='失物表';

-- ----------------------------
-- Table structure for super_admins
-- ----------------------------
DROP TABLE IF EXISTS `super_admins`;
CREATE TABLE `super_admins` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '超级管理员ID',
  `name` varchar(100) NOT NULL COMMENT '管理员名称',
  `password` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '密码',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `id` (`id`) USING BTREE,
  UNIQUE KEY `name` (`name`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='超级管理员表';

-- ----------------------------
-- Table structure for user
-- ----------------------------
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '用户ID',
  `name` varchar(50) NOT NULL COMMENT '姓名',
  `student_id` varchar(12) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '学号',
  `password` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '密码',
  `is_admin` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否为管理员',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `avatar_url` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '头像url',
  `email` varchar(100) NOT NULL COMMENT '邮箱',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `student_id` (`student_id`) USING BTREE,
  UNIQUE KEY `uk_user_email` (`email`),
  KEY `idx_student_id` (`student_id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=23 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='用户表';

SET FOREIGN_KEY_CHECKS = 1;
