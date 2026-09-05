"""Фірмові кольори брендів з каталогу artline.ua (https://artline.ua/uk/brands).

Кожен рядок - колір ЛОГОТИПА бренду (як на білому), а не готовий токен палітри:
у пресет він потрапляє через pipeline.palette_from_accent - ту саму математику,
що й палітра з фото. Тож акцент доводиться до 4.5:1 на власних темних картках,
темні поверхні лише підфарбовуються відтінком бренду, світле тло - блідий тон.

Джерело hex - brandfetch.com (первинний колір бренду), для кількох брендів,
де brandfetch віддає колір сайту замість логотипа (LG, JBL, Trust, Hikvision,
Anker, AOC...), узято колір з брендбука/логотипа - такі рядки позначені.
Бренди з монохромним логотипом (Apple, Fractal Design, Sennheiser, Synology,
DJI-подібні чорно-білі) тут відсутні: для них працює фірмовий циан або палітра
з фото. Це стартові пресети - у вкладці «Кольори» вони правляться як звичайні;
сид додає лише відсутні за назвою і ніколи не переписує правлені.
"""

BRAND_ACCENTS = [
    ('2E', '#41AECC'),
    ('A4Tech', '#FFA509'),
    ('Acer', '#83B81A'),
    ('AeroCool', '#21A9FF'),
    ('Ajax Systems', '#5AE4AA'),
    ('Amazfit', '#FFFC00'),
    ('AMD', '#ED1C24'),
    ('Anker', '#00A7E1'),  # брендбук/логотип, не brandfetch
    ('Antec', '#FCCA00'),
    ('ANYCUBIC', '#41649A'),
    ('AOC', '#E1251B'),  # брендбук/логотип, не brandfetch
    ('Apacer', '#02A1C1'),
    ('APC', '#009530'),
    ('ASRock', '#79BD28'),
    ('ASUS ROG', '#E4002B'),
    ('Bambu Lab', '#00AE42'),
    ('Baseus', '#FCEB55'),  # брендбук/логотип, не brandfetch
    ('be quiet!', '#F07E00'),
    ('Belkin', '#205BA9'),
    ('BenQ', '#502E91'),
    ('BLUETTI', '#00A2E4'),
    ('Brother', '#0D2EA0'),
    ('Canon', '#CC0100'),
    ('Canyon', '#EA3725'),
    ('Cisco', '#00BCEB'),
    ('Cooler Master', '#5B2D8E'),
    ('Corsair', '#ECE81A'),
    ('COUGAR', '#FF6000'),
    ('Creality', '#00C651'),  # ребрендинг 2024: зелений замість старого синього
    ('Crucial', '#0068FF'),
    ('D-Link', '#00A0DF'),  # брендбук/логотип, не brandfetch
    ('Dahua', '#E60012'),
    ('DeepCool', '#12807F'),
    ('Dell', '#007DB8'),
    ('DEYE', '#015CBB'),
    ('DJI', '#0971CE'),
    ('DXRacer', '#D80027'),
    ('Dyness', '#56C500'),
    ('Eaton', '#005EB8'),
    ('EcoFlow', '#CC8B4C'),
    ('Ecovacs', '#184586'),
    ('Edifier', '#5ABEF4'),
    ('EKWB', '#F89828'),
    ('ELEGOO', '#7A90CB'),
    ('Elgato', '#204CFE'),
    ('ENERMAX', '#EB1924'),
    ('EPOS', '#3D80C5'),
    ('Epson', '#0C2F87'),
    ('eSUN', '#00AB84'),
    ('FIFINE', '#3F2385'),
    ('G.SKILL', '#B20C0C'),
    ('GIGABYTE AORUS', '#F58220'),
    ('GOODRAM', '#0056B3'),
    ('GoPro', '#00B4EA'),
    ('Govee', '#3C5EF2'),
    ('Growatt', '#80B645'),
    ('HATOR', '#F7BC60'),
    ('Hikvision', '#E60012'),  # брендбук/логотип, не brandfetch
    ('Hisense', '#00A4A0'),
    ('HONOR', '#256FFF'),  # брендбук/логотип, не brandfetch
    ('HP', '#0096D6'),
    ('Huawei', '#C7000B'),
    ('Huion', '#00BFD6'),
    ('HyperX', '#C8102E'),
    ('HYTE', '#02CBB9'),
    ('ID-COOLING', '#EA5404'),
    ('iiyama', '#599AD7'),
    ('INNO3D', '#1461B3'),
    ('Intel', '#0071C5'),
    ('JA Solar', '#00459C'),
    ('Jabra', '#FFD100'),
    ('Jackery', '#FD5000'),
    ('JBL', '#FF6600'),  # брендбук/логотип, не brandfetch
    ('Jinko Solar', '#2EAB47'),
    ('Keenetic', '#309DD8'),
    ('Keychron', '#488282'),
    ('Kingston', '#C8102E'),
    ('Kingston FURY', '#C8102E'),
    ('KIOXIA', '#1ABCEF'),
    ('Koss', '#C93428'),
    ('Kyocera', '#DF0522'),
    ('Lenovo', '#E2231A'),
    ('Lexar', '#0C5EA8'),  # брендбук/логотип, не brandfetch
    ('LG', '#A50034'),  # брендбук/логотип, не brandfetch
    ('Lian Li', '#5897FB'),
    ('Logitech', '#00B8FC'),
    ('LONGi', '#E4002B'),  # брендбук/логотип, не brandfetch
    ('Marshall', '#9C4221'),
    ('Mercusys', '#DB9F60'),
    ('Microsoft', '#00A4EF'),
    ('MikroTik', '#A2351A'),
    ('Motorola', '#D07158'),
    ('MSI', '#D10000'),
    ('Netis', '#0089CF'),  # брендбук/логотип, не brandfetch
    ('Noctua', '#551805'),
    ('Nokia', '#005AFF'),
    ('NVIDIA', '#76B900'),
    ('NZXT', '#8160BB'),
    ('OnePlus', '#F50514'),
    ('Palit', '#1E4FA3'),  # брендбук/логотип, не brandfetch
    ('Pantum', '#D2232A'),
    ('Patriot', '#0055CC'),
    ('Philips', '#0C5ED7'),
    ('PNY', '#192595'),
    ('PocketBook', '#96521E'),
    ('Polymaker', '#47B4BE'),
    ('PowerColor', '#FF0000'),
    ('Pylontech', '#E4002B'),  # брендбук/логотип, не brandfetch
    ('QNAP', '#FFC107'),
    ('Rapoo', '#6C16FA'),
    ('Razer', '#44D62C'),
    ('realme', '#FFC915'),
    ('Redragon', '#E30613'),  # брендбук/логотип, не brandfetch
    ('Roborock', '#E53935'),  # брендбук/логотип, не brandfetch
    ('Samsung', '#1428A0'),
    ('SanDisk', '#E10600'),
    ('Sapphire', '#0B4EA2'),  # брендбук/логотип, не brandfetch
    ('Seagate', '#70BF4E'),
    ('Seasonic', '#0085CA'),
    ('Secretlab', '#A72A2F'),
    ('Segway-Ninebot', '#F30000'),
    ('Solidigm', '#4F00B5'),
    ('Solis', '#E30613'),  # брендбук/логотип, не brandfetch
    ('Sony', '#2D61BF'),
    ('SteelSeries', '#FC4E03'),
    ('Sungrow', '#FF7900'),
    ('TCL', '#FA2727'),
    ('Team Group', '#E4002B'),  # брендбук/логотип, не brandfetch
    ('Tenda', '#FC5101'),
    ('Thermal Grizzly', '#E54225'),
    ('Thermaltake', '#3072B3'),
    ('TP-Link', '#4ACBD6'),
    ('Transcend', '#428BCA'),
    ('Trust', '#E2001A'),  # брендбук/логотип, не brandfetch
    ('Ubiquiti', '#2282FF'),
    ('UGREEN', '#8B0000'),
    ('ViewSonic', '#A41A4A'),
    ('Vinga', '#25ABF2'),
    ('Wacom', '#00A0E1'),  # брендбук/логотип, не brandfetch
    ('Western Digital', '#2266FF'),
    ('Xerox', '#D92231'),
    ('XFX', '#ED1C24'),
    ('Xiaomi', '#FF6900'),
    ('XPG', '#DD00F8'),
    ('XPPen', '#FF6C00'),
    ('Zalman', '#0292B4'),
    ('Zotac', '#F5A500'),  # брендбук/логотип, не brandfetch
    ('Zyxel', '#0072BC'),  # брендбук/логотип, не brandfetch
]

# Попередні hex брендів, які змінили айдентику. Сид перевіряє: якщо пресет у
# базі досі дорівнює палітрі зі СТАРОГО hex (оператор його не правив), він
# оновлюється до нового; правлений руками пресет лишається як є.
BRAND_PREVIOUS = {
    'Creality': ['#005BAC'],  # синій логотип до ребрендингу 2024
}
