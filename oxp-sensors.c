// SPDX-License-Identifier: GPL-2.0+
/*
 * Platform driver for OneXPlayer Super X systems that expose fan reading and
 * fan control through EC-backed hwmon sysfs nodes.
 */

#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/hwmon.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/platform_device.h>
#include <linux/processor.h>

/* Handle ACPI lock mechanism */
static u32 oxp_mutex;

#define ACPI_LOCK_DELAY_MS	500

static bool lock_global_acpi_lock(void)
{
	return ACPI_SUCCESS(acpi_acquire_global_lock(ACPI_LOCK_DELAY_MS, &oxp_mutex));
}

static bool unlock_global_acpi_lock(void)
{
	return ACPI_SUCCESS(acpi_release_global_lock(oxp_mutex));
}

/* Fan reading and PWM */
#define OXP_SENSOR_FAN_REG		0x76 /* Fan reading is 2 registers long */
#define OXP_SENSOR_PWM_ENABLE_REG	0x4A /* PWM enable is 1 register long */
#define OXP_SENSOR_PWM_REG		0x4B /* PWM reading is 1 register long */

/* Turbo button takeover function
 * Older boards have different values and EC registers
 * for the same function
 */
#define OXP_OLD_TURBO_SWITCH_REG	0x1E
#define OXP_OLD_TURBO_TAKE_VAL		0x01
#define OXP_OLD_TURBO_RETURN_VAL	0x00

#define OXP_TURBO_SWITCH_REG		0xF1
#define OXP_TURBO_TAKE_VAL		0x40
#define OXP_TURBO_RETURN_VAL		0x00

#define OXP_LED_ENABLE_VAL		0x01
#define OXP_LED_DISABLE_VAL		0x00

#define OXP_LED_MODE_STATIC		0x00
#define OXP_LED_MODE_BREATHING		0x01
#define OXP_LED_MODE_RAINBOW		0x02

static int led_enable_reg = -1;
static int led_mode_reg = -1;
static int led_brightness_reg = -1;
static int led_red_reg = -1;
static int led_green_reg = -1;
static int led_blue_reg = -1;

module_param(led_enable_reg, int, 0644);
MODULE_PARM_DESC(led_enable_reg, "EC register for LED enable");
module_param(led_mode_reg, int, 0644);
MODULE_PARM_DESC(led_mode_reg, "EC register for LED mode");
module_param(led_brightness_reg, int, 0644);
MODULE_PARM_DESC(led_brightness_reg, "EC register for LED brightness");
module_param(led_red_reg, int, 0644);
MODULE_PARM_DESC(led_red_reg, "EC register for LED red channel");
module_param(led_green_reg, int, 0644);
MODULE_PARM_DESC(led_green_reg, "EC register for LED green channel");
module_param(led_blue_reg, int, 0644);
MODULE_PARM_DESC(led_blue_reg, "EC register for LED blue channel");

static bool led_regs_valid;

static const struct dmi_system_id dmi_table[] = {
	{
		.matches = {
			DMI_MATCH(DMI_BOARD_VENDOR, "ONE-NETBOOK"),
			DMI_EXACT_MATCH(DMI_BOARD_NAME, "ONEXPLAYER SUPER X"),
		},
	},
	{},
};

/* Helper functions to handle EC read/write */
static int read_from_ec(u8 reg, int size, long *val)
{
	int i;
	int ret;
	u8 buffer;

	if (!lock_global_acpi_lock())
		return -EBUSY;

	*val = 0;
	for (i = 0; i < size; i++) {
		ret = ec_read(reg + i, &buffer);
		if (ret)
			return ret;
		*val <<= i * 8;
		*val += buffer;
	}

	if (!unlock_global_acpi_lock())
		return -EBUSY;

	return 0;
}

static int write_to_ec(u8 reg, u8 value)
{
	int ret;

	if (!lock_global_acpi_lock())
		return -EBUSY;

	ret = ec_write(reg, value);

	if (!unlock_global_acpi_lock())
		return -EBUSY;

	return ret;
}

static bool led_map_complete(void)
{
	return led_enable_reg >= 0 && led_enable_reg <= 0xFF &&
	       led_mode_reg >= 0 && led_mode_reg <= 0xFF &&
	       led_brightness_reg >= 0 && led_brightness_reg <= 0xFF &&
	       led_red_reg >= 0 && led_red_reg <= 0xFF &&
	       led_green_reg >= 0 && led_green_reg <= 0xFF &&
	       led_blue_reg >= 0 && led_blue_reg <= 0xFF;
}

/* Turbo button toggle functions */
static int tt_toggle_enable(void)
{
	return write_to_ec(OXP_TURBO_SWITCH_REG, OXP_TURBO_TAKE_VAL);
}

static int tt_toggle_disable(void)
{
	return write_to_ec(OXP_TURBO_SWITCH_REG, OXP_TURBO_RETURN_VAL);
}

/* Callbacks for turbo toggle attribute */
static ssize_t tt_toggle_store(struct device *dev,
			       struct device_attribute *attr, const char *buf,
			       size_t count)
{
	int rval;
	bool value;

	rval = kstrtobool(buf, &value);
	if (rval)
		return rval;

	if (value) {
		rval = tt_toggle_enable();
	} else {
		rval = tt_toggle_disable();
	}
	if (rval)
		return rval;

	return count;
}

static ssize_t tt_toggle_show(struct device *dev,
			      struct device_attribute *attr, char *buf)
{
	int retval;
	long val;

	retval = read_from_ec(OXP_TURBO_SWITCH_REG, 1, &val);
	if (retval)
		return retval;

	return sysfs_emit(buf, "%d\n", !!val);
}

static DEVICE_ATTR_RW(tt_toggle);

/* LED control functions */
static int led_enable(void)
{
	if (!led_regs_valid)
		return -EOPNOTSUPP;
	return write_to_ec((u8)led_enable_reg, OXP_LED_ENABLE_VAL);
}

static int led_disable(void)
{
	if (!led_regs_valid)
		return -EOPNOTSUPP;
	return write_to_ec((u8)led_enable_reg, OXP_LED_DISABLE_VAL);
}

static int led_set_mode(long mode)
{
	if (!led_regs_valid)
		return -EOPNOTSUPP;
	if (mode < OXP_LED_MODE_STATIC || mode > OXP_LED_MODE_RAINBOW)
		return -EINVAL;
	return write_to_ec((u8)led_mode_reg, (u8)mode);
}

static int led_set_brightness(long brightness)
{
	if (!led_regs_valid)
		return -EOPNOTSUPP;
	if (brightness < 0 || brightness > 255)
		return -EINVAL;
	return write_to_ec((u8)led_brightness_reg, (u8)brightness);
}

static int led_set_color(u8 red, u8 green, u8 blue)
{
	int ret;
	if (!led_regs_valid)
		return -EOPNOTSUPP;
	ret = write_to_ec((u8)led_red_reg, red);
	if (ret)
		return ret;
	ret = write_to_ec((u8)led_green_reg, green);
	if (ret)
		return ret;
	return write_to_ec((u8)led_blue_reg, blue);
}

/* LED sysfs callbacks */
static ssize_t led_enable_store(struct device *dev,
				struct device_attribute *attr, const char *buf,
				size_t count)
{
	int rval;
	bool value;

	rval = kstrtobool(buf, &value);
	if (rval)
		return rval;

	if (value)
		rval = led_enable();
	else
		rval = led_disable();

	if (rval)
		return rval;

	return count;
}

static ssize_t led_enable_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	long val;
	int retval;

	if (!led_regs_valid)
		return -EOPNOTSUPP;
	retval = read_from_ec((u8)led_enable_reg, 1, &val);
	if (retval)
		return retval;

	return sysfs_emit(buf, "%d\n", !!val);
}

static ssize_t led_mode_store(struct device *dev,
			      struct device_attribute *attr, const char *buf,
			      size_t count)
{
	int rval;
	long value;

	rval = kstrtol(buf, 0, &value);
	if (rval)
		return rval;

	rval = led_set_mode(value);
	if (rval)
		return rval;

	return count;
}

static ssize_t led_mode_show(struct device *dev,
			     struct device_attribute *attr, char *buf)
{
	long val;
	int retval;

	if (!led_regs_valid)
		return -EOPNOTSUPP;
	retval = read_from_ec((u8)led_mode_reg, 1, &val);
	if (retval)
		return retval;

	return sysfs_emit(buf, "%ld\n", val);
}

static ssize_t led_brightness_store(struct device *dev,
				    struct device_attribute *attr, const char *buf,
				    size_t count)
{
	int rval;
	long value;

	rval = kstrtol(buf, 0, &value);
	if (rval)
		return rval;

	rval = led_set_brightness(value);
	if (rval)
		return rval;

	return count;
}

static ssize_t led_brightness_show(struct device *dev,
				   struct device_attribute *attr, char *buf)
{
	long val;
	int retval;

	if (!led_regs_valid)
		return -EOPNOTSUPP;
	retval = read_from_ec((u8)led_brightness_reg, 1, &val);
	if (retval)
		return retval;

	return sysfs_emit(buf, "%ld\n", val);
}

static ssize_t led_color_store(struct device *dev,
			       struct device_attribute *attr, const char *buf,
			       size_t count)
{
	int rval;
	u8 red, green, blue;

	rval = sscanf(buf, "%hhu %hhu %hhu", &red, &green, &blue);
	if (rval != 3)
		return -EINVAL;

	rval = led_set_color(red, green, blue);
	if (rval)
		return rval;

	return count;
}

static ssize_t led_color_show(struct device *dev,
			      struct device_attribute *attr, char *buf)
{
	long red, green, blue;
	int retval;

	if (!led_regs_valid)
		return -EOPNOTSUPP;
	retval = read_from_ec((u8)led_red_reg, 1, &red);
	if (retval)
		return retval;
	retval = read_from_ec((u8)led_green_reg, 1, &green);
	if (retval)
		return retval;
	retval = read_from_ec((u8)led_blue_reg, 1, &blue);
	if (retval)
		return retval;

	return sysfs_emit(buf, "%ld %ld %ld\n", red, green, blue);
}

static DEVICE_ATTR_RW(led_enable);
static DEVICE_ATTR_RW(led_mode);
static DEVICE_ATTR_RW(led_brightness);
static DEVICE_ATTR_RW(led_color);

/* PWM enable/disable functions */
static int oxp_pwm_enable(void)
{
	return write_to_ec(OXP_SENSOR_PWM_ENABLE_REG, 0x01);
}

static int oxp_pwm_disable(void)
{
	return write_to_ec(OXP_SENSOR_PWM_ENABLE_REG, 0x00);
}

/* Callbacks for hwmon interface */
static umode_t oxp_ec_hwmon_is_visible(const void *drvdata,
				       enum hwmon_sensor_types type, u32 attr, int channel)
{
	switch (type) {
	case hwmon_fan:
		return 0444;
	case hwmon_pwm:
		return 0644;
	default:
		return 0;
	}
}

static int oxp_platform_read(struct device *dev, enum hwmon_sensor_types type,
			     u32 attr, int channel, long *val)
{
	int ret;

	switch (type) {
	case hwmon_fan:
		switch (attr) {
		case hwmon_fan_input:
			return read_from_ec(OXP_SENSOR_FAN_REG, 2, val);
		default:
			break;
		}
		break;
	case hwmon_pwm:
		switch (attr) {
		case hwmon_pwm_input:
			ret = read_from_ec(OXP_SENSOR_PWM_REG, 1, val);
			if (ret)
				return ret;
			return 0;
		case hwmon_pwm_enable:
			return read_from_ec(OXP_SENSOR_PWM_ENABLE_REG, 1, val);
		default:
			break;
		}
		break;
	default:
		break;
	}
	return -EOPNOTSUPP;
}

static int oxp_platform_write(struct device *dev, enum hwmon_sensor_types type,
			      u32 attr, int channel, long val)
{
	switch (type) {
	case hwmon_pwm:
		switch (attr) {
		case hwmon_pwm_enable:
			if (val == 1)
				return oxp_pwm_enable();
			else if (val == 0)
				return oxp_pwm_disable();
			return -EINVAL;
		case hwmon_pwm_input:
			if (val < 0 || val > 255)
				return -EINVAL;
			return write_to_ec(OXP_SENSOR_PWM_REG, val);
		default:
			break;
		}
		break;
	default:
		break;
	}
	return -EOPNOTSUPP;
}

/* Known sensors in the OXP EC controllers */
static const struct hwmon_channel_info * const oxp_platform_sensors[] = {
	HWMON_CHANNEL_INFO(fan,
			   HWMON_F_INPUT),
	HWMON_CHANNEL_INFO(pwm,
			   HWMON_PWM_INPUT | HWMON_PWM_ENABLE),
	NULL,
};

static struct attribute *oxp_ec_attrs[] = {
	&dev_attr_tt_toggle.attr,
	&dev_attr_led_enable.attr,
	&dev_attr_led_mode.attr,
	&dev_attr_led_brightness.attr,
	&dev_attr_led_color.attr,
	NULL
};

ATTRIBUTE_GROUPS(oxp_ec);

static const struct hwmon_ops oxp_ec_hwmon_ops = {
	.is_visible = oxp_ec_hwmon_is_visible,
	.read = oxp_platform_read,
	.write = oxp_platform_write,
};

static const struct hwmon_chip_info oxp_ec_chip_info = {
	.ops = &oxp_ec_hwmon_ops,
	.info = oxp_platform_sensors,
};

/* Initialization logic */
static int oxp_platform_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct device *hwdev;
	int ret;

	if (!dmi_first_match(dmi_table) || boot_cpu_data.x86_vendor != X86_VENDOR_AMD)
		return -ENODEV;

	led_regs_valid = led_map_complete();

	if (led_regs_valid) {
		ret = devm_device_add_group(dev, &oxp_ec_group);
		if (ret)
			return ret;
	}

	hwdev = devm_hwmon_device_register_with_info(dev, "oxpec", NULL,
						     &oxp_ec_chip_info, NULL);

	return PTR_ERR_OR_ZERO(hwdev);
}

static struct platform_driver oxp_platform_driver = {
	.driver = {
		.name = "oxp-platform",
	},
	.probe = oxp_platform_probe,
};

static struct platform_device *oxp_platform_device;

static int __init oxp_platform_init(void)
{
	oxp_platform_device =
		platform_create_bundle(&oxp_platform_driver,
				       oxp_platform_probe, NULL, 0, NULL, 0);

	return PTR_ERR_OR_ZERO(oxp_platform_device);
}

static void __exit oxp_platform_exit(void)
{
	platform_device_unregister(oxp_platform_device);
	platform_driver_unregister(&oxp_platform_driver);
}

MODULE_DEVICE_TABLE(dmi, dmi_table);

module_init(oxp_platform_init);
module_exit(oxp_platform_exit);

MODULE_AUTHOR("Joaquín Ignacio Aramendía <samsagax@gmail.com>");
MODULE_DESCRIPTION("Platform driver that handles EC sensors of OneXPlayer Super X");
MODULE_LICENSE("GPL");
