-- =============================================================
-- Schéma de Base de Données : CosmandBot
-- MariaDB 10.5+ / MySQL 8.0+
-- Encodage : utf8mb4 / utf8mb4_unicode_ci
-- =============================================================

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT NOT NULL PRIMARY KEY,
    welcome_channel_id BIGINT NULL,
    log_channel_id BIGINT NULL,
    mod_role_id BIGINT NULL,
    birthday_channel BIGINT NULL,
    birthday_hour INT DEFAULT 9,
    countdown_channel_id BIGINT NULL,
    countdown_hour INT DEFAULT 9,
    countdown_minute INT DEFAULT 0,
    goodday_channel BIGINT NULL,
    goodday_hour INT DEFAULT 8,
    timezone VARCHAR(50) DEFAULT 'Europe/Paris'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    event_date VARCHAR(100) NOT NULL,
    location VARCHAR(255) NOT NULL,
    max_slots INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_events_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS event_participants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_id INT NOT NULL,
    user_id BIGINT NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_event_user (event_id, user_id),
    INDEX idx_event_part_event (event_id),
    INDEX idx_event_part_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS conventions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    title VARCHAR(150) NOT NULL,
    role_name VARCHAR(100) NOT NULL,
    role_prefix VARCHAR(100) NULL,
    location VARCHAR(255) NOT NULL,
    description TEXT NULL,
    days_json TEXT NOT NULL,
    dedicated_channel_id BIGINT NULL,
    meetup_days_json TEXT NULL,
    meetup_roles_json TEXT NULL,
    extra_messages_json TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_conv_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS convention_participants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    convention_id INT NOT NULL,
    user_id BIGINT NOT NULL,
    day_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_conv_user_day (convention_id, user_id, day_name),
    INDEX idx_conv_part_conv (convention_id),
    INDEX idx_conv_part_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS countdowns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    event_date DATETIME NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_countdowns_guild (guild_id, event_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS birthdays (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    member_id BIGINT NOT NULL,
    display_name VARCHAR(255) NULL,
    date VARCHAR(10) NOT NULL,
    is_custom TINYINT(1) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_birthdays_date (guild_id, date),
    INDEX idx_birthdays_member (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    run_at DATETIME NOT NULL,
    sent TINYINT(1) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_scheduled_due (sent, run_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS daily_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_daily_guild (guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

