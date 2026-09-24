
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from captcha_solver import converter
import sunburst_navigator as sn
import session_status as ss

URL = "https://dld.srmist.edu.in/ktretecurricula/#/ktretecurricula/student/home"

START_LEARNING_XPATH = "/html/body/div[1]/div/section/section/main[1]/div/div/div/div[1]/button"
USERNAME_XPATH = "/html/body/div[3]/div/div[2]/div/div[2]/div/div/div/div/div[3]/div[2]/div[1]/span/input"
PASSWORD_XPATH = "/html/body/div[3]/div/div[2]/div/div[2]/div/div/div/div/div[3]/div[2]/div[2]/span/input"

WAIT_TIMEOUT = 30
POST_LOGIN_DELAY_SECONDS = 10

USERNAME = "REGNO"
PASSWORD = "PASS"


def build_driver() -> webdriver.Chrome:
    options = Options()
    # Non-headless: no "--headless" argument, so a visible browser window opens.
    options.add_argument("--start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=options)


def main() -> None:
    driver = build_driver()
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        driver.get(URL)

        start_learning_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, START_LEARNING_XPATH))
        )
        start_learning_btn.click()

        username_input = wait.until(
            EC.visibility_of_element_located((By.XPATH, USERNAME_XPATH))
        )
        username_input.clear()
        username_input.send_keys(USERNAME)

        password_input = wait.until(
            EC.visibility_of_element_located((By.XPATH, PASSWORD_XPATH))
        )
        password_input.clear()
        password_input.send_keys(PASSWORD)

        captcha_=wait.until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/div[3]/div/div[2]/div/div[2]/div/div/div/div/div[3]/div[2]/div[3]/div/canvas'))
        )
        captcha_input=wait.until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/div[3]/div/div[2]/div/div[2]/div/div/div/div/div[3]/div[2]/div[4]/span/input'))
        )
        captcha_.screenshot("captcha.png")
        time.sleep(2)
        captcha_input.send_keys(converter())
        print(f"Credentials entered. Waiting {POST_LOGIN_DELAY_SECONDS}s before continuing...")
        login_btn=wait.until(
            EC.visibility_of_element_located((By.XPATH, '/html/body/div[3]/div/div[2]/div/div[2]/div/div/div/div/div[3]/div[2]/div[5]/button'))
        )
        login_btn.click()
        time.sleep(2)
        sem=wait.until(
            EC.visibility_of_element_located((By.XPATH, "//*[contains(text(), 'SEM 3')]"))
        )
        sem.click()
        time.sleep(2)
        subject = wait.until(
            EC.visibility_of_element_located((By.XPATH, "//*[contains(text(), 'TRANSFORMS AND BOUNDARY VALUE PROBLEMS')]"))
        )
        print("subject:", subject)

        card = subject.find_element(
            By.XPATH, "./ancestor::div[contains(@class, 'ant-card') and contains(@class, 'ant-card-hoverable')][1]"
        )
        print("card:", card)

        action_items = card.find_elements(By.XPATH, ".//ul[contains(@class, 'ant-card-actions')]/li")
        print(f"Found {len(action_items)} action items")

        for i, li in enumerate(action_items):
            label_spans = li.find_elements(By.XPATH, ".//span[@role='img']")
            label = label_spans[0].get_attribute("aria-label") if label_spans else None
            print(f"  [{i}] aria-label={label}")

        target_li = action_items[3]  # li[4] in your xpath = index 3 here
        svg_el = target_li.find_element(By.TAG_NAME, "svg")
        print("Clicking svg in li[4] (aria-label above tells you which icon this is):", svg_el)
        svg_el.click()
        print("Clicked.")
        time.sleep(2)
        
        print("Logged in. Browser left open for you to continue.")

        input("Press Enter to close the browser...")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
