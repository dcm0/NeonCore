from mycroft.configuration import Configuration, get_private_keys
from mycroft.util.log import LOG
import boto3


def get_lang_config():
    config = Configuration.get()
    lang_config = config.get("language", {})
    lang_config["internal"] = lang_config.get("internal") or config.get("lang", "en-us")
    lang_config["user"] = lang_config.get("user") or config.get("lang", "en-us")
    return lang_config


class LanguageDetector:
    def __init__(self):
        self.config = get_lang_config()
        self.default_language = self.config["user"].split("-")[0]
        # hint_language: str  E.g., 'ITALIAN' or 'it' boosts Italian
        self.hint_language = self.config["user"].split("-")[0]
        self.boost = self.config["boost"]

    def detect(self, text):
        # assume default language
        return self.default_language


class LanguageTranslator:
    def __init__(self):
        self.config = get_lang_config()
        self.boost = self.config["boost"]
        self.default_language = self.config["user"].split("-")[0]
        self.internal_language = self.config["internal"]

    def translate(self, text, target=None, source=None):
        return text


class Pycld2Detector(LanguageDetector):
    def __init__(self):
        super().__init__()
        from jarbas_utils.lang.detect import detect_lang_naive
        self._detect = detect_lang_naive

    def detect(self, text):
        if self.boost:
            return self._detect(text, hint_language=self.hint_language) or \
                   self.default_language
        else:
            return self._detect(text) or \
                   self.default_language


class Pycld3Detector(LanguageDetector):
    def __init__(self):
        super().__init__()
        from jarbas_utils.lang.detect import detect_lang_neural
        self._detect = detect_lang_neural

    def detect(self, text):
        if self.boost:
            return self._detect(text, hint_language=self.hint_language) or \
                   self.default_language
        else:
            return self._detect(text) or \
                   self.default_language


class GoogleDetector(LanguageDetector):
    def __init__(self):
        super().__init__()
        from jarbas_utils.lang.detect import detect_lang_google
        import logging
        logging.getLogger("hyper.http20.connection").setLevel("ERROR")
        self._detect = detect_lang_google

    def detect(self, text):
        return self._detect(text) or self.default_language


class GoogleTranslator(LanguageTranslator):
    def __init__(self):
        super().__init__()
        from jarbas_utils.lang.translate import translate_text
        self._translate = translate_text

    def translate(self, text, target=None, source=None):
        if self.boost and not source:
            source = self.default_language
        target = target or self.internal_language
        return self._translate(text, target, source)


class AmazonTranslator(LanguageTranslator):
    def __init__(self):
        super().__init__()
        self.keys = get_private_keys()["amazon"]
        self.client = boto3.Session(aws_access_key_id=self.keys["key_id"],
                                    aws_secret_access_key=self.keys["secret_key"],
                                    region_name=self.keys["region"]).client('translate')

    def translate(self, text, target=None, source="auto"):
        target = target or self.internal_language

        response = self.client.translate_text(
            Text=text,
            SourceLanguageCode="auto",
            TargetLanguageCode=target.split("-")[0]
        )
        return response["TranslatedText"]


class AmazonDetector(LanguageDetector):
    def __init__(self):
        super().__init__()
        self.keys = get_private_keys()["amazon"]
        self.client = boto3.Session(aws_access_key_id=self.keys["key_id"],
                                    aws_secret_access_key=self.keys["secret_key"],
                                    region_name=self.keys["region"]).client('comprehend')

    def detect(self, text):
        response = self.client.detect_dominant_language(
            Text=text
        )
        return response['Languages'][0]['LanguageCode']


class TranslatorFactory:
    CLASSES = {
        "google": GoogleTranslator,
        "amazon": AmazonTranslator
    }

    @staticmethod
    def create(module=None):
        config = Configuration.get().get("language", {})
        module = module or config.get("translation_module", "google")
        try:
            clazz = TranslatorFactory.CLASSES.get(module)
            return clazz()
        except Exception as e:
            # The translate backend failed to start. Report it and fall back to
            # default.
            LOG.exception('The selected translator backend could not be loaded, '
                          'falling back to default...')
            if module != 'google':
                return GoogleTranslator()
            else:
                raise


class DetectorFactory:
    CLASSES = {
        "amazon": AmazonDetector,
        "google": GoogleDetector,
        "cld2": Pycld2Detector,
        "cld3": Pycld3Detector
    }

    @staticmethod
    def create(module=None):
        config = Configuration.get().get("language", {})
        module = module or config.get("detection_module", "cld3")
        try:
            clazz = DetectorFactory.CLASSES.get(module)
            return clazz()
        except Exception as e:
            # The translate backend failed to start. Report it and fall back to
            # default.
            LOG.exception('The selected language detector backend could not be loaded, '
                          'falling back to default...')
            if module != 'cld3':
                return Pycld3Detector()
            else:
                raise


if __name__ == "__main__":
    texts = ["My name is neon",
             "O meu nome é jarbas"]

    d = AmazonDetector()
    assert d.detect(texts[0]) == "en"
    assert d.detect(texts[1]) == "pt"

    t = AmazonTranslator()
    assert t.translate(texts[1]) == "My name is jarbas"

    t = TranslatorFactory.create()
    assert t.translate(texts[1]) == "My name is jarbas"

    d = DetectorFactory.create()
    assert d.detect(texts[0]) == "en"
    assert d.detect(texts[1]) == "pt"

    d = DetectorFactory.create("cld3")
    assert d.detect(texts[0]) == "en"
    assert d.detect(texts[1]) == "pt"

    d = DetectorFactory.create("google")
    assert d.detect(texts[0]) == "en"
    assert d.detect(texts[1]) == "pt"

    # failure cases
    texts = ["My name is jarbas",
             "O meu nome é neon"]

    d = Pycld2Detector()
    assert d.detect(texts[1]) != "pt"

    d = Pycld3Detector()
    assert d.detect(texts[0]) != "en"