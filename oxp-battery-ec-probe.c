#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define EC_BASE 0xFE800400UL
#define EC_SIZE 0x100UL
#define OFFS_CHARGE_LIMIT 0xA3
#define OFFS_BYPASS_MODE 0xA4
#define OFFS_FORCE_CHARGE_MIN 0xA5
#define OFFS_POWER_SUPPLY_MODE 0xFE

static uint32_t read_u8(const uint8_t *data, size_t offset) {
    return data[offset];
}

static int write_u8(uint8_t *data, size_t offset, uint8_t value) {
    data[offset] = value;
    return 0;
}

static const char *power_supply_mode_name(uint32_t mode) {
    switch (mode) {
    case 1:
        return "OnlyBattery";
    case 2:
        return "OnlyTypec100";
    case 3:
        return "BatteryTypec100";
    case 4:
        return "DCIn";
    case 5:
        return "BatteryDCIn";
    case 8:
        return "Typec65";
    case 9:
        return "BatteryTypec65";
    case 500:
        return "BatteryLow";
    case 501:
        return "BatteryOverheat";
    case 1000:
        return "Unknown";
    default:
        return "unmapped";
    }
}

static int parse_charge_limit(const char *text, uint8_t *value) {
    char *end = NULL;
    long parsed = strtol(text, &end, 10);
    static const int allowed[] = {50, 60, 70, 75, 80, 85, 90, 95, 100};
    size_t i;

    if (!text || *text == '\0' || (end && *end != '\0')) {
        return -1;
    }

    for (i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++) {
        if (parsed == allowed[i]) {
            *value = (uint8_t)parsed;
            return 0;
        }
    }

    return -1;
}

static int parse_bypass_mode(const char *text, uint8_t *value) {
    if (strcmp(text, "off") == 0 || strcmp(text, "0") == 0) {
        *value = 0;
        return 0;
    }
    if (strcmp(text, "mode1") == 0 || strcmp(text, "1") == 0) {
        *value = 1;
        return 0;
    }
    if (strcmp(text, "mode2") == 0 || strcmp(text, "3") == 0) {
        *value = 3;
        return 0;
    }
    return -1;
}

int main(int argc, char **argv) {
    long page_size = sysconf(_SC_PAGE_SIZE);
    int write_mode = 0;
    uint8_t write_value = 0;
    size_t write_offset = 0;
    if (page_size <= 0) {
        fprintf(stderr, "failed to get page size\n");
        return 1;
    }

    if (argc == 3 && strcmp(argv[1], "set-charge-limit") == 0) {
        if (parse_charge_limit(argv[2], &write_value) != 0) {
            fprintf(stderr, "invalid charge limit\n");
            return 2;
        }
        write_mode = 1;
        write_offset = OFFS_CHARGE_LIMIT;
    } else if (argc == 3 && strcmp(argv[1], "set-bypass-mode") == 0) {
        if (parse_bypass_mode(argv[2], &write_value) != 0) {
            fprintf(stderr, "invalid bypass mode\n");
            return 2;
        }
        write_mode = 1;
        write_offset = OFFS_BYPASS_MODE;
    } else if (argc != 1 && !(argc == 2 && strcmp(argv[1], "get") == 0)) {
        fprintf(stderr, "usage: %s [get|set-charge-limit <percent>|set-bypass-mode <off|mode1|mode2>]\n", argv[0]);
        return 2;
    }

    off_t page_base = (off_t)(EC_BASE & ~((unsigned long)page_size - 1UL));
    off_t page_offset = (off_t)(EC_BASE - (unsigned long)page_base);
    size_t map_size = (size_t)page_offset + EC_SIZE;

    int fd = open("/dev/mem", write_mode ? (O_RDWR | O_SYNC) : (O_RDONLY | O_SYNC));
    if (fd < 0) {
        fprintf(stderr, "open /dev/mem failed: %s\n", strerror(errno));
        return 1;
    }

    void *map = mmap(NULL, map_size, write_mode ? (PROT_READ | PROT_WRITE) : PROT_READ, MAP_SHARED, fd, page_base);
    if (map == MAP_FAILED) {
        fprintf(stderr, "mmap failed: %s\n", strerror(errno));
        close(fd);
        return 1;
    }

    uint8_t *data = (uint8_t *)map + page_offset;

    if (write_mode) {
        write_u8(data, write_offset, write_value);
        msync(map, map_size, MS_SYNC);
    }

    uint32_t charge_limit = read_u8(data, OFFS_CHARGE_LIMIT);
    uint32_t bypass_mode = read_u8(data, OFFS_BYPASS_MODE);
    uint32_t force_charge_min = read_u8(data, OFFS_FORCE_CHARGE_MIN);
    uint32_t power_supply_mode = read_u8(data, OFFS_POWER_SUPPLY_MODE);

    printf("{\n");
    printf("  \"charge_limit_percent\": %u,\n", charge_limit);
    printf("  \"bypass_power_mode\": %u,\n", bypass_mode);
    printf("  \"force_charge_min\": %u,\n", force_charge_min);
    printf("  \"write_applied\": %s,\n", write_mode ? "true" : "false");
    printf("  \"power_supply_mode\": {\n");
    printf("    \"value\": %u,\n", power_supply_mode);
    printf("    \"name\": \"%s\"\n", power_supply_mode_name(power_supply_mode));
    printf("  }\n");
    printf("}\n");

    munmap(map, map_size);
    close(fd);
    return 0;
}
