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

/*
 * Battery charge-limit / bypass helper for the OneXPlayer Super X.
 *
 * Primary backend: the in-tree oxpec platform driver extends the standard
 * BAT0 power-supply device with charge_control_end_threshold and
 * charge_behaviour attributes.  Going through the kernel works under Secure
 * Boot kernel lockdown, where direct /dev/mem EC access is denied even for
 * root.  The legacy EC memory path is kept as a fallback for kernels without
 * the driver.
 *
 * Bypass-mode mapping between the widget and the kernel:
 *   off   <-> auto                  (normal charging)
 *   mode1 <-> inhibit-charge        (battery bypassed until re-enabled)
 *   mode2 <-> inhibit-charge-awake  (bypassed while the system is awake)
 */

#define BAT0_DIR "/sys/class/power_supply/BAT0"
#define SYS_CHARGE_LIMIT BAT0_DIR "/charge_control_end_threshold"
#define SYS_CHARGE_BEHAVIOUR BAT0_DIR "/charge_behaviour"
#define SYS_BAT_STATUS BAT0_DIR "/status"
#define SYS_AC_ONLINE "/sys/class/power_supply/ACAD/online"

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

static int read_sysfs(const char *path, char *buf, size_t len) {
    int fd = open(path, O_RDONLY);
    ssize_t n;

    if (fd < 0)
        return -1;
    n = read(fd, buf, len - 1);
    close(fd);
    if (n <= 0)
        return -1;
    buf[n] = '\0';
    return 0;
}

static int write_sysfs(const char *path, const char *value) {
    int fd = open(path, O_WRONLY);
    ssize_t n;

    if (fd < 0)
        return -1;
    n = write(fd, value, strlen(value));
    close(fd);
    return (n == (ssize_t)strlen(value)) ? 0 : -1;
}

static int kernel_backend_available(void) {
    char probe[16];

    /* open() uses the effective (setuid root) credentials; access() would
     * check the real user and wrongly fail on root-only sysfs attributes. */
    return read_sysfs(SYS_CHARGE_LIMIT, probe, sizeof(probe)) == 0 &&
           read_sysfs(SYS_CHARGE_BEHAVIOUR, probe, sizeof(probe)) == 0;
}

/* charge_behaviour lists the active setting in brackets, e.g. "[auto] inhibit-charge". */
static int active_behaviour(char *out, size_t len) {
    char text[256];
    char *start, *end;

    if (read_sysfs(SYS_CHARGE_BEHAVIOUR, text, sizeof(text)) != 0)
        return -1;
    start = strchr(text, '[');
    end = start ? strchr(start + 1, ']') : NULL;
    if (!start || !end || (size_t)(end - start - 1) >= len)
        return -1;
    memcpy(out, start + 1, (size_t)(end - start - 1));
    out[end - start - 1] = '\0';
    return 0;
}

static int bypass_from_behaviour(const char *behaviour) {
    if (strcmp(behaviour, "auto") == 0)
        return 0;
    if (strcmp(behaviour, "inhibit-charge") == 0)
        return 1;
    if (strcmp(behaviour, "inhibit-charge-awake") == 0)
        return 3;
    return -1;
}

static const char *behaviour_from_bypass(uint8_t mode) {
    switch (mode) {
    case 0:
        return "auto";
    case 1:
        return "inhibit-charge";
    case 3:
        return "inhibit-charge-awake";
    default:
        return NULL;
    }
}

/* Synthesize a display-friendly power source description from standard sysfs. */
static const char *kernel_power_source_name(void) {
    char status[32] = {0};
    char online[8] = {0};
    int ac = -1;

    if (read_sysfs(SYS_AC_ONLINE, online, sizeof(online)) == 0)
        ac = atoi(online);
    if (read_sysfs(SYS_BAT_STATUS, status, sizeof(status)) != 0)
        return power_supply_mode_name(1000);
    if (strncmp(status, "Discharging", 11) == 0 || ac == 0)
        return "Battery";
    if (strncmp(status, "Charging", 8) == 0)
        return "AC (charging)";
    if (strncmp(status, "Not charging", 12) == 0)
        return "AC (charge inhibited)";
    if (strncmp(status, "Full", 4) == 0)
        return "AC (full)";
    return power_supply_mode_name(1000);
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
    if (strcmp(text, "off") == 0 || strcmp(text, "0") == 0 ||
        strcmp(text, "auto") == 0) {
        *value = 0;
        return 0;
    }
    if (strcmp(text, "mode1") == 0 || strcmp(text, "1") == 0 ||
        strcmp(text, "inhibit-charge") == 0) {
        *value = 1;
        return 0;
    }
    if (strcmp(text, "mode2") == 0 || strcmp(text, "3") == 0 ||
        strcmp(text, "inhibit-charge-awake") == 0) {
        *value = 3;
        return 0;
    }
    return -1;
}

static int run_kernel_backend(int write_mode, const char *write_path,
                              const char *write_value) {
    char limit[16] = {0};
    char behaviour[64] = {0};
    uint32_t charge_limit, bypass_mode, power_supply_mode;

    if (write_mode && write_sysfs(write_path, write_value) != 0) {
        fprintf(stderr, "write %s failed: %s\n", write_path, strerror(errno));
        return 1;
    }

    if (read_sysfs(SYS_CHARGE_LIMIT, limit, sizeof(limit)) != 0)
        charge_limit = 0;
    else
        charge_limit = (uint32_t)atoi(limit);

    if (active_behaviour(behaviour, sizeof(behaviour)) != 0)
        bypass_mode = 0;
    else
        bypass_mode = (uint32_t)bypass_from_behaviour(behaviour);

    power_supply_mode = 1000;

    printf("{\n");
    printf("  \"backend\": \"kernel\",\n");
    printf("  \"charge_limit_percent\": %u,\n", charge_limit);
    printf("  \"bypass_power_mode\": %u,\n", bypass_mode);
    printf("  \"force_charge_min\": 0,\n");
    printf("  \"write_applied\": %s,\n", write_mode ? "true" : "false");
    printf("  \"power_supply_mode\": {\n");
    printf("    \"value\": %u,\n", power_supply_mode);
    printf("    \"name\": \"%s\"\n", kernel_power_source_name());
    printf("  }\n");
    printf("}\n");
    return 0;
}

int main(int argc, char **argv) {
    long page_size = sysconf(_SC_PAGE_SIZE);
    int write_mode = 0;
    uint8_t write_value = 0;
    size_t write_offset = 0;
    const char *kernel_write_path = NULL;
    const char *kernel_write_value = NULL;
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
        kernel_write_path = SYS_CHARGE_LIMIT;
        kernel_write_value = argv[2];
    } else if (argc == 3 && strcmp(argv[1], "set-bypass-mode") == 0) {
        if (parse_bypass_mode(argv[2], &write_value) != 0) {
            fprintf(stderr, "invalid bypass mode\n");
            return 2;
        }
        write_mode = 1;
        write_offset = OFFS_BYPASS_MODE;
        kernel_write_path = SYS_CHARGE_BEHAVIOUR;
        kernel_write_value = behaviour_from_bypass(write_value);
    } else if (argc != 1 && !(argc == 2 && strcmp(argv[1], "get") == 0)) {
        fprintf(stderr, "usage: %s [get|set-charge-limit <percent>|set-bypass-mode <off|mode1|mode2>]\n", argv[0]);
        return 2;
    }

    if (kernel_backend_available())
        return run_kernel_backend(write_mode, kernel_write_path, kernel_write_value);

    off_t page_base = (off_t)(EC_BASE & ~((unsigned long)page_size - 1UL));
    off_t page_offset = (off_t)(EC_BASE - (unsigned long)page_base);
    size_t map_size = (size_t)page_offset + EC_SIZE;

    int fd = open("/dev/mem", write_mode ? (O_RDWR | O_SYNC) : (O_RDONLY | O_SYNC));
    if (fd < 0) {
        fprintf(stderr, "open /dev/mem failed: %s\n", strerror(errno));
        fprintf(stderr, "hint: the kernel oxpec battery attributes are not available and direct EC access is blocked\n");
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
    printf("  \"backend\": \"ec\",\n");
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
