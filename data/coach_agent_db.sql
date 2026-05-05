CREATE DATABASE IF NOT EXISTS coach_agent_db 
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE coach_agent_db;

-- 1. 维度表：身体部位
CREATE TABLE body_parts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    name_zh VARCHAR(100) UNIQUE NOT NULL -- 中文名称
);

-- 2. 维度表：器材
CREATE TABLE equipments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    name_zh VARCHAR(100) UNIQUE NOT NULL -- 中文名称
);

-- 3. 维度表：目标肌肉（包括主要和次要）
CREATE TABLE targets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    name_zh VARCHAR(100) UNIQUE NOT NULL -- 中文名称
);

-- 4. 类别表：运动类别
CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    name_zh VARCHAR(100) UNIQUE NOT NULL -- 中文名称
);

-- 4. 核心动作表
CREATE TABLE exercises (
    id VARCHAR(50) PRIMARY KEY, 
    name VARCHAR(255) NOT NULL,
    name_zh VARCHAR(255) NOT NULL,
    body_part_id INT,
    equipment_id INT,
    target_id INT,
    local_gif_path VARCHAR(255),
    -- 修正默认值语法
    difficulty ENUM('beginner', 'intermediate', 'advanced') DEFAULT 'beginner',
    category_id INT,
    instructions JSON,
    instructions_zh JSON,
    description TEXT,
    description_zh TEXT,
    
    FOREIGN KEY (body_part_id) REFERENCES body_parts(id),
    FOREIGN KEY (equipment_id) REFERENCES equipments(id),
    FOREIGN KEY (target_id) REFERENCES targets(id),
    FOREIGN KEY (category_id) REFERENCES categories(id),
    
    INDEX idx_difficulty (difficulty),
    INDEX idx_body_part_id (body_part_id),
    INDEX idx_equipment_id (equipment_id),
    INDEX idx_target_id (target_id),
    INDEX idx_category_id (category_id),
    INDEX idx_bodypart_equipment (body_part_id, equipment_id),
    INDEX idx_target_equipment (target_id, equipment_id)
);


-- 5. 中间表：辅助肌肉（处理多对多关系）
CREATE TABLE exercise_secondary_muscles (
    exercise_id VARCHAR(50),
    target_id INT,
    PRIMARY KEY (exercise_id, target_id),
    FOREIGN KEY (exercise_id) REFERENCES exercises(id),
    FOREIGN KEY (target_id) REFERENCES targets(id)
);

-- 6. 用户表
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    gender ENUM('male', 'female', 'other') DEFAULT 'other',
    weight_kg DECIMAL(5, 2),
    height_cm DECIMAL(5, 2),
    fitness_level ENUM('beginner', 'intermediate', 'advanced') DEFAULT 'beginner',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fitness_level (fitness_level)
);
