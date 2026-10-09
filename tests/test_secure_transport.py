"""Real loopback TLS tests; embedded private keys are PUBLIC TEST FIXTURES ONLY.

These disposable, self-signed identities were generated with OpenSSL 3.0.13.
They must never identify a real host or protect player credentials. No external
certificate generator, cryptography package, system trust, or Internet is needed.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import secrets
import ssl
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.protocol import encode_message, read_message
from emerald_multiplayer.secure_transport import (
    ClientTlsConfig, HostIdentityError, ServerTlsConfig, is_numeric_unicast_address,
)
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore
from test_companion import make_files
from test_flash import make_flash
from emerald_multiplayer.protocol import PROTOCOL_VERSION

_TEST_IDENTITIES = (('-----BEGIN CERTIFICATE-----\nMIIDUjCCAjqgAwIBAgIUFQ2ajyD899WtpeUXbnzM8lHOIJAwDQYJKoZIhvcNAQEL\nBQAwJTEjMCEGA1UEAwwaUFVCTElDIFRFU1QgRklYVFVSRSBPTkxZIDAwIBcNMjYx\nMDA4MDUzNDA3WhgPMjEyNjA5MTQwNTM0MDdaMCUxIzAhBgNVBAMMGlBVQkxJQyBU\nRVNUIEZJWFRVUkUgT05MWSAwMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKC\nAQEAr/8GWO7mdDcn+VjnnIA4ddg3rWTuAQDuy8rQN2Xbr8f/A+1uRcBNTu6YHwhW\nSJf7tpn7Tb+2LmA0MQsulbBZW+ylas/KiSIm6pk6KaMLaix0EhjjAs8Cv8nbdjSs\nTZiYgsfLdPV86C0x7rJD/rFlyFHYF7xcQEeQzW0570NuniA0rSKFni+hqIQjrgYM\nEaUkzYgQodyG1cZUrm6GLlDnNwNfrImK9lc6Eql//zXSM5/fyhmi/+aHOu8rSb8c\noLbTgv91OTG/AdwGEcNQR7OCoioKz+dFDMo3fxkttq0p0SKkOjzbGeUnaRfRQIxM\nD/wgPJLtZHT/sUn5CFRl6VHdUQIDAQABo3gwdjAdBgNVHQ4EFgQUNWxTBlUW3lCx\n8k3Hy2fWyeqlGvIwHwYDVR0jBBgwFoAUNWxTBlUW3lCx8k3Hy2fWyeqlGvIwDwYD\nVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAqQwEwYDVR0lBAwwCgYIKwYBBQUH\nAwEwDQYJKoZIhvcNAQELBQADggEBACAg96tt3xqZL5PJS32cV+79cyLexsA37egt\nmj4xBiUlpGZE8VbZn63GPbquRL4NnNkGz5BBIL9a1NiGD1DXz/xhOmcyVeLzokup\nuOqc0TVmR5HC5eXtZTL4WWv3KlWsXYO1gpDm/Vkx+hr5WzQs28TRV32dRC3Qw0dq\n0yCKC2F5+m4uDAOtcElVJcjQHK3P0otPI9CeAPEOlW9UQepgjZHBphZaWFQsf92B\nXJsJNn8LZvcLjpWo25xuSwx0CTh+XG5VSM/aCdgnyO0Nzotj8phBSlfovClzXDOT\nG/V+jD1Q1UadrhUGb2YJysrOilfRlD0/kRcFfThk5keo2rGk4UY=\n-----END CERTIFICATE-----\n', '-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCv/wZY7uZ0Nyf5\nWOecgDh12DetZO4BAO7LytA3Zduvx/8D7W5FwE1O7pgfCFZIl/u2mftNv7YuYDQx\nCy6VsFlb7KVqz8qJIibqmTopowtqLHQSGOMCzwK/ydt2NKxNmJiCx8t09XzoLTHu\nskP+sWXIUdgXvFxAR5DNbTnvQ26eIDStIoWeL6GohCOuBgwRpSTNiBCh3IbVxlSu\nboYuUOc3A1+siYr2VzoSqX//NdIzn9/KGaL/5oc67ytJvxygttOC/3U5Mb8B3AYR\nw1BHs4KiKgrP50UMyjd/GS22rSnRIqQ6PNsZ5SdpF9FAjEwP/CA8ku1kdP+xSfkI\nVGXpUd1RAgMBAAECggEALIREVcBv+FtvOAn9478nCN/dDXXnIcfbnx641hpknCzp\nW1P2PZxrsZh2T/sq4AfZepGuWDcy3L4m1XTvnptRrwfHu6G9qDxEPbjuVlPQclW2\nMlGrMi2sk1h6s4aVQrdjdEkXNIlXw96Sr77Vphm3FhlloHNbnkK75MpJCjUzSLmO\n+fS7GuVbEtIj1xDhCHUaRNtmaT+9mg45Dk/w9Duy+ktVd4fP1LaIR2VfrRAs8VK/\nEOUSFE1drM4tmGdzki2bGxXZKzF5H63kb4V1DVVuXfXJUEdaNxrhl0U9NoMzeaUM\n65d0W+XcVD0i8HYEz86Ih3sgN1+0EVYshCR49NwtZQKBgQDmjLBBeIDHoTgC7JRW\nx4hnxFi0+RPLcqxsiwn5eEzL5lHwkwR08iBspFR0fCGYQB6AQx0/jvqRUwf/ikjN\nlNj9Mi90MYOZAk8RTmg0/eRcQd1bMTwtxbsjc2A3ZLShj/AsJUBSOH500Oq7W6Bd\nVYP0j0xbYQACphD3LVi6EGN/twKBgQDDbKmZCyj90qYK9ldQfL9/T3yta6CNJ1bT\n+g0699MKb57r4cQaiH5xbBU3tBEXYcIiq/BnrqQO1A+YPfSqGsA+bBnlL3uNT2Qf\ncP/kESwDh9DnzPy/D0L00UnbcAg4/Np3NQ5TbTBFz9NnoA/Bmzz42nufPZIPmxYz\naEmYdg/7NwKBgG+O5DrJ9IaknFXN5HmZU4fimon3fHyVoJllLg5pB8AiUsP2X9G2\n17m6SqOS7S6e2CN4Vk7LALQRWW1tnIzd2aGrBwtSajs/wsK9De+Wa0m5FUNrL5N2\nendM/OHQ+Ra0b6Ls45Llg0tDTFIcpByFpLRSIsCUz0x4zvzMFIL0KzFBAoGARsyU\nOPT5GdP6AdizU16OhhIHClEGrnzFETDzIBzuoUZFHhIB2NcAcBkHKtIaqwzop2UB\nSJ7VouWi7LXtcL8WTMcfLo/gRBayIE3w9vBdsL3AqmnyW0mtKUK1bkGNSRAaGbvn\n/8N8DJ65aT5s1uhl04Zb6RoGU48NIPy0RP7o1UsCgYATtpE2ep8rJJjATjFF/eCu\ncCRA5Ae2qlojULN1HRpXgsDmdRSq7okXG+lvJ6srg/yKEZneukUMtk1ptNAohIIH\n2KG6pB9bjK0MvZUUPRNMLMgINzWIQfFI5IGGYCWJZ+HpIXvhv8e8wzOjuGobXT/v\ncfQeqJZ43ep0gXIpZt3YYA==\n-----END PRIVATE KEY-----\n'), ('-----BEGIN CERTIFICATE-----\nMIIDUjCCAjqgAwIBAgIUaHcMm60c4PUqDOcnpIokXZf+dGUwDQYJKoZIhvcNAQEL\nBQAwJTEjMCEGA1UEAwwaUFVCTElDIFRFU1QgRklYVFVSRSBPTkxZIDEwIBcNMjYx\nMDA4MDUzNDA3WhgPMjEyNjA5MTQwNTM0MDdaMCUxIzAhBgNVBAMMGlBVQkxJQyBU\nRVNUIEZJWFRVUkUgT05MWSAxMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKC\nAQEArvvXCyDMpZ0LSLRahS8mE+a3A13qdII5kJ/NsqCqZQ+y5UaO5jYOkwiOVSxw\ntHkrPB0OxGrULOk4qiE7ISOJIXQTc/q52mg43Sj3lv8+ESRc2pQgiDa3nz16gI45\naahWOlJuS4I0SktWBvuJOP+u9ydKaM8monEZvqarodlmv1pSJ6oeuxxtP8CerMLX\nbkaqillaHbHBwLeK4RY9M8oOzQP0yCJ/lmSA/uOl8I6eEgi3tKfpiECaFRywL4dM\nFLuzx0mVgZqSTtXPwrdvK/lkaW9BHL/gcYoLbS6RTMqX8B61HUqehfbCTaZbjgmG\nO7frrygw+a47eOmC0BEqyhI18wIDAQABo3gwdjAdBgNVHQ4EFgQUmNSKCxVrt7m7\nWXyYM/61O5l3lp8wHwYDVR0jBBgwFoAUmNSKCxVrt7m7WXyYM/61O5l3lp8wDwYD\nVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAqQwEwYDVR0lBAwwCgYIKwYBBQUH\nAwEwDQYJKoZIhvcNAQELBQADggEBACUfQ21ccgBJsuY7i1VVgo13lMdChIW3yvFp\nxxSTUKzZ5f7wvpE0Q9TmdJo7wraw43v9KKHsqtqjgF+ubp4o+vikZOuFAgyfe99s\njdAkls/9aGs9gTWLWTED+yrJMGAoq2Mbfn6ZMg4hhMaHTVlB1Ax1iZ29+jUyXLVX\nKzGfYUqT67EakCpWNLLJtQ2v9UlQkP7hWZaG0xAJSknDXWeo+WWLJQJziCgv+joX\nHtpIRG8htHQ8Bv3LtR4z/a6Xf3lrUfPKFtuYE02QxR8Lu5ZUtubHqDDCLuCc9ftC\nDuHhi/RKgKERWl+pTNc06W4biY2d2uBA1JolJAoTx3JWQr5T2fM=\n-----END CERTIFICATE-----\n', '-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCu+9cLIMylnQtI\ntFqFLyYT5rcDXep0gjmQn82yoKplD7LlRo7mNg6TCI5VLHC0eSs8HQ7EatQs6Tiq\nITshI4khdBNz+rnaaDjdKPeW/z4RJFzalCCINrefPXqAjjlpqFY6Um5LgjRKS1YG\n+4k4/673J0pozyaicRm+pquh2Wa/WlInqh67HG0/wJ6swtduRqqKWVodscHAt4rh\nFj0zyg7NA/TIIn+WZID+46Xwjp4SCLe0p+mIQJoVHLAvh0wUu7PHSZWBmpJO1c/C\nt28r+WRpb0Ecv+BxigttLpFMypfwHrUdSp6F9sJNpluOCYY7t+uvKDD5rjt46YLQ\nESrKEjXzAgMBAAECggEAM29ThrHdddDzwCtDcGKrjq4Cnbq9cAHXaeuPSzJu48X5\nj+ttlb3OCuo47FBj0KjNTJ49+P5t38WuIlQiTVtks7CrByxr9Qctr9Sa8oeUdvV5\nVca0yVVMJEKt/5vOxH/22K3iPc/IDw6V+vd1HowJohyqgqRhdt5H8wKK8Mg2q4gk\npz7PyR3Gm5W/jbVflAHe+B7+te8hTBUFCgGkeYHuZYnbpQagBaqfggbwuI/OruNL\n7w79qJiJ+JA1VLEC96PPxvePOl+Y1t44gWCRY/xgSQy7C1jAW4eX4sfwDv8W/VZX\ncqbUnE1HL8MP7j/aJq6iJawPVzif34LiOH79T16sAQKBgQDY2ybuC7jeHOL7LHm2\nSxfwk7ll2jP65Ozjx0AHH7fykItEnQy5arWJYtxTYaHrof0etpb3EOdSqgr+RRMW\nrIfTBnv1gyJfYytZTg7YG5WtDWRmPBumiezmbKnmqnATdUcujjNDM5KWYM+UTQv9\nljxlXIuFbZdFwZtgbuAkz3Cg2QKBgQDOkcgzIZnINTMtqUG5QIFl2Aiv8hW1D8z6\nCZaoHBC6wUCKH5K682i7ezLfv2VfGy6JcIaSeME34cp+ZURELQC/3Z9nMpQCkaHA\n4TBroMqR3ZIHokrEsROH8nzC/m5stp/3jkN8cxxCE9NhY6ar2vJ6JVjGuDWyNLeS\ntPMSi7HNqwKBgAqVz/WortJwuIeoKRzD15xPqaoWF5l0mTeZHz/5xWHaumGUBO38\nDnZxU+3iAyRcWN2p7f6LXa9ES5sTxhXCQDMFywE18HSVg6UtUT4tQoYa9D6lSng7\nnUu2HCj9QtFAVUQpfskV+F7MxPUpOZ+cOMB93vWZXtvx0mLHprtFQOspAoGBALYk\nT03ek9W4Kx9Y/g3V9gMSQV667C8R9qCGceRbktjJbBoeiufzluaxVAN8pWr98cPY\nh6CBf4XBvyZCLraao+2KAnMhYub8+I61QVe1mMiTgZ7fmGPk657UzvO1GzMauOS0\n+YazjTgqeRmHn8ArN+FCKwxWA2rWFwPyL96rdKUvAoGBAM2ykYbmY179y28N2Nn0\nGdKQ1yqUepymRiHfV7d6nyKLiEpDFwn3FMrnzi4vtwa6EyCKVjQng7JIZiyAQ/0E\nFWx3KLk/hVNH71/oAIe+RzyYCahF4es4h9aIwJLe9K9ZB0zyqja3aUXwLQyXXa4X\nMLtGBBmDEMV5kJxNmITUu3Tj\n-----END PRIVATE KEY-----\n'), ('-----BEGIN CERTIFICATE-----\nMIIDUDCCAjigAwIBAgIUaHcMm60c4PUqDOcnpIokXZf+dGUwDQYJKoZIhvcNAQEL\nBQAwJTEjMCEGA1UEAwwaUFVCTElDIFRFU1QgRklYVFVSRSBPTkxZIDEwHhcNMjYx\nMDA4MDUzNjE1WhcNMjYxMDA3MDUzNjE1WjAlMSMwIQYDVQQDDBpQVUJMSUMgVEVT\nVCBGSVhUVVJFIE9OTFkgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEB\nAK771wsgzKWdC0i0WoUvJhPmtwNd6nSCOZCfzbKgqmUPsuVGjuY2DpMIjlUscLR5\nKzwdDsRq1CzpOKohOyEjiSF0E3P6udpoON0o95b/PhEkXNqUIIg2t589eoCOOWmo\nVjpSbkuCNEpLVgb7iTj/rvcnSmjPJqJxGb6mq6HZZr9aUieqHrscbT/AnqzC125G\nqopZWh2xwcC3iuEWPTPKDs0D9Mgif5ZkgP7jpfCOnhIIt7Sn6YhAmhUcsC+HTBS7\ns8dJlYGakk7Vz8K3byv5ZGlvQRy/4HGKC20ukUzKl/AetR1KnoX2wk2mW44Jhju3\n668oMPmuO3jpgtARKsoSNfMCAwEAAaN4MHYwHQYDVR0OBBYEFJjUigsVa7e5u1l8\nmDP+tTuZd5afMB8GA1UdIwQYMBaAFJjUigsVa7e5u1l8mDP+tTuZd5afMA8GA1Ud\nEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgKkMBMGA1UdJQQMMAoGCCsGAQUFBwMB\nMA0GCSqGSIb3DQEBCwUAA4IBAQAXA9hdPSM0rjK/loBE0GX+Axk5MRNOVA8N8XrS\nAwq6Ysk2AV6XxyXnlP3574DBk6cUPG9CJmCD8hEplxf/HGrMmA0eo30fJiUGszij\nOq0BkmFqnzzx8W7dmMGf9aFed8gZRg1kXguEbh7iROB9VSp8Mxt0YgwZmAQKP+su\nbYtvKAiyUpHVnfiMm8NP7jTsJAbDaiZop9GsrWkNzWBaWrsEr/iX0DLYsaePa5ih\nsV+CcHRW9Wh+ty2fVO3dOqBV9zzw3w5mneIyvGLTWnEuzi7MIRtkDuRuUnLnGYQT\n47zvLH4L0k+6Tqoer+LGfs5ti7mFPl4vwDjyhdiVV6KfRV7W\n-----END CERTIFICATE-----\n', '-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCu+9cLIMylnQtI\ntFqFLyYT5rcDXep0gjmQn82yoKplD7LlRo7mNg6TCI5VLHC0eSs8HQ7EatQs6Tiq\nITshI4khdBNz+rnaaDjdKPeW/z4RJFzalCCINrefPXqAjjlpqFY6Um5LgjRKS1YG\n+4k4/673J0pozyaicRm+pquh2Wa/WlInqh67HG0/wJ6swtduRqqKWVodscHAt4rh\nFj0zyg7NA/TIIn+WZID+46Xwjp4SCLe0p+mIQJoVHLAvh0wUu7PHSZWBmpJO1c/C\nt28r+WRpb0Ecv+BxigttLpFMypfwHrUdSp6F9sJNpluOCYY7t+uvKDD5rjt46YLQ\nESrKEjXzAgMBAAECggEAM29ThrHdddDzwCtDcGKrjq4Cnbq9cAHXaeuPSzJu48X5\nj+ttlb3OCuo47FBj0KjNTJ49+P5t38WuIlQiTVtks7CrByxr9Qctr9Sa8oeUdvV5\nVca0yVVMJEKt/5vOxH/22K3iPc/IDw6V+vd1HowJohyqgqRhdt5H8wKK8Mg2q4gk\npz7PyR3Gm5W/jbVflAHe+B7+te8hTBUFCgGkeYHuZYnbpQagBaqfggbwuI/OruNL\n7w79qJiJ+JA1VLEC96PPxvePOl+Y1t44gWCRY/xgSQy7C1jAW4eX4sfwDv8W/VZX\ncqbUnE1HL8MP7j/aJq6iJawPVzif34LiOH79T16sAQKBgQDY2ybuC7jeHOL7LHm2\nSxfwk7ll2jP65Ozjx0AHH7fykItEnQy5arWJYtxTYaHrof0etpb3EOdSqgr+RRMW\nrIfTBnv1gyJfYytZTg7YG5WtDWRmPBumiezmbKnmqnATdUcujjNDM5KWYM+UTQv9\nljxlXIuFbZdFwZtgbuAkz3Cg2QKBgQDOkcgzIZnINTMtqUG5QIFl2Aiv8hW1D8z6\nCZaoHBC6wUCKH5K682i7ezLfv2VfGy6JcIaSeME34cp+ZURELQC/3Z9nMpQCkaHA\n4TBroMqR3ZIHokrEsROH8nzC/m5stp/3jkN8cxxCE9NhY6ar2vJ6JVjGuDWyNLeS\ntPMSi7HNqwKBgAqVz/WortJwuIeoKRzD15xPqaoWF5l0mTeZHz/5xWHaumGUBO38\nDnZxU+3iAyRcWN2p7f6LXa9ES5sTxhXCQDMFywE18HSVg6UtUT4tQoYa9D6lSng7\nnUu2HCj9QtFAVUQpfskV+F7MxPUpOZ+cOMB93vWZXtvx0mLHprtFQOspAoGBALYk\nT03ek9W4Kx9Y/g3V9gMSQV667C8R9qCGceRbktjJbBoeiufzluaxVAN8pWr98cPY\nh6CBf4XBvyZCLraao+2KAnMhYub8+I61QVe1mMiTgZ7fmGPk657UzvO1GzMauOS0\n+YazjTgqeRmHn8ArN+FCKwxWA2rWFwPyL96rdKUvAoGBAM2ykYbmY179y28N2Nn0\nGdKQ1yqUepymRiHfV7d6nyKLiEpDFwn3FMrnzi4vtwa6EyCKVjQng7JIZiyAQ/0E\nFWx3KLk/hVNH71/oAIe+RzyYCahF4es4h9aIwJLe9K9ZB0zyqja3aUXwLQyXXa4X\nMLtGBBmDEMV5kJxNmITUu3Tj\n-----END PRIVATE KEY-----\n'))


def certificates(directory):
    paths = []
    for index, (certificate, key) in enumerate(_TEST_IDENTITIES):
        cert_path, key_path = Path(directory) / f"test-{index}.pem", Path(directory) / f"test-{index}.key"
        cert_path.write_text(certificate, encoding="ascii")
        key_path.write_text(key, encoding="ascii")
        digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest()
        paths.append((cert_path, key_path, digest))
    return paths


async def wait_until(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class SecureTransportConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.identities = certificates(self.temp.name)
        self.rom, self.manifest = make_files(self.temp.name)
        self.config = CompanionConfig(self.rom, self.manifest, str(uuid4()), "Player", secrets.token_bytes(32))

    def test_contexts_require_chain_validation_tls12_dedicated_trust_and_no_keylog(self):
        cert, key, pin = self.identities[0]
        with patch.dict(os.environ, {"SSLKEYLOGFILE": str(Path(self.temp.name) / "must-not-exist.log")}):
            client = ClientTlsConfig(cert, pin).build_context()
            server = ServerTlsConfig(cert, key).build_context()
        self.assertEqual(client.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(client.check_hostname)  # Exact host certificate pin replaces DNS identity.
        self.assertEqual(client.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(server.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(client.get_ca_certs(binary_form=True), [ssl.PEM_cert_to_DER_cert(_TEST_IDENTITIES[0][0])])
        self.assertIsNone(client.keylog_filename)
        self.assertIsNone(server.keylog_filename)
        self.assertFalse((Path(self.temp.name) / "must-not-exist.log").exists())

    def test_public_opt_ins_require_tls_credential_and_specific_numeric_addresses(self):
        cert, _, pin = self.identities[0]
        tls = ClientTlsConfig(cert, pin)
        credential = secrets.token_bytes(32)
        for changes in (dict(server_host="8.8.8.8"), dict(server_host="8.8.8.8", public_server=True),
                        dict(server_host="8.8.8.8", public_server=True, server_tls=tls),
                        dict(public_server=1), dict(server_tls=True)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.config, **changes)
        for host in ("0.0.0.0", "::", "255.255.255.255", "224.0.0.1", "ff02::1", "example.com", "fe80::1%3", "100.64.0.1"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                replace(self.config, server_host=host, public_server=True, server_tls=tls, server_credential=credential)
        for host in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "192.168.1.2", "fd00::2", "8.8.8.8", "2606:4700:4700::1111"):
            self.assertTrue(is_numeric_unicast_address(host))
            replace(self.config, server_host=host, public_server=True, server_tls=tls, server_credential=credential)

    def test_pin_durations_files_world_uuid_and_secret_representation(self):
        cert, key, pin = self.identities[0]
        for bad_pin in (pin.upper(), "0" * 63, b"0" * 64, "zz" * 32):
            with self.assertRaises(ValueError):
                ClientTlsConfig(cert, bad_pin)
        for duration in (0, -1, True, float("nan"), float("inf"), 31):
            with self.assertRaises(ValueError):
                ClientTlsConfig(cert, pin, handshake_timeout=duration)
            with self.assertRaises(ValueError):
                ServerTlsConfig(cert, key, handshake_timeout=duration)
        for world in ("invalid", str(uuid4()).upper(), str(uuid4())):
            with self.assertRaises(ValueError):
                replace(self.config, expected_world_id=world)
        replace(self.config, expected_world_id=str(uuid4()), server_credential=secrets.token_bytes(32))
        self.assertNotIn(str(key), repr(ServerTlsConfig(cert, key)))
        self.assertNotIn(self.config.token.hex(), repr(self.config))
        with self.assertRaises(ValueError):
            ClientTlsConfig(Path(self.temp.name) / "absent.pem", pin).build_context()
        oversized = Path(self.temp.name) / "oversized.pem"
        oversized.write_bytes(b"x" * 65_537)
        with self.assertRaises(ValueError):
            ClientTlsConfig(oversized, pin).build_context()
        with self.assertRaises(ssl.SSLError):
            ServerTlsConfig(cert, self.identities[1][1]).build_context()


class SecureTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.previous_loop_handler = self.loop.get_exception_handler()
        self.expected_tls_rejection = False
        self.unexpected_loop_errors = []
        def observe_loop_error(loop, context):
            # Asyncio debug mode reports handshake refusals before _accept can
            # run. Capture only the failures explicitly exercised by a test;
            # any unrelated background failure still fails the test.
            if (self.expected_tls_rejection
                    and context.get("message") == "Error on transport creation for incoming connection"
                    and isinstance(context.get("exception"), (ssl.SSLError, ConnectionError))):
                return
            self.unexpected_loop_errors.append((context.get("message"), type(context.get("exception")).__name__))
        self.loop.set_exception_handler(observe_loop_error)
        self.temp = tempfile.TemporaryDirectory()
        self.identities = certificates(self.temp.name)
        self.rom, self.manifest = make_files(self.temp.name)
        self.base = CompanionConfig(self.rom, self.manifest, str(uuid4()), "Player", secrets.token_bytes(32), ipc_port=0)
        self.store = CheckpointStore(Path(self.temp.name) / "world.sqlite3", self.base.build_id, BASELINE_RULESET, LAYOUT_ID)
        self.player = self.store.create_player("TLS Player")
        self.config = ServerConfig(self.base.build_id, BASELINE_RULESET, heartbeat_interval=0.1,
                                   idle_timeout=3, handshake_timeout=1, send_timeout=1)
        cert, key, pin = self.identities[0]
        self.server_tls = ServerTlsConfig(cert, key, handshake_timeout=0.3, shutdown_timeout=0.3)
        self.client_tls = ClientTlsConfig(cert, pin, handshake_timeout=1, shutdown_timeout=0.3)
        self.server = WorldServer(self.config, store=self.store)
        self.companions = []
        self.listeners = []
        self.writers = []

    async def asyncTearDown(self):
        for companion in self.companions:
            await companion.close()
        for writer in self.writers:
            writer.close()
            with suppress(ConnectionError, OSError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 1)
        for listener in self.listeners:
            listener.close()
            await listener.wait_closed()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()
        self.loop.set_exception_handler(self.previous_loop_handler)
        self.assertEqual(self.unexpected_loop_errors, [])

    def companion(self, address, **changes):
        config = replace(self.base, player_id=self.player.player_id, server_credential=self.player.credential,
                         server_host=address[0], server_port=address[1], server_tls=self.client_tls,
                         **changes)
        companion = Companion(config)
        self.companions.append(companion)
        return companion

    async def test_correct_pin_real_companion_checkpoint_and_heartbeat(self):
        await self.server.start("127.0.0.1", 0, tls=self.server_tls, public=True)
        c = self.companion(self.server.address, public_server=True, expected_world_id=self.store.metadata.world_id)
        await c.start()
        await wait_until(lambda: c.connected)
        peer = c._remote_writer.get_extra_info("ssl_object")
        self.assertIn(peer.version(), ("TLSv1.2", "TLSv1.3"))
        self.assertEqual(c.world_id, self.store.metadata.world_id)
        client = CheckpointClient(c)
        payload = make_flash(with_rtc=True)
        result = await client.upload(payload, expected_revision=0)
        self.assertEqual(result["revision"], 1)
        downloaded = await client.download()
        self.assertEqual(downloaded.payload, payload)
        await asyncio.sleep(0.35)
        self.assertTrue(c.connected)
        self.assertEqual(set(self.server.sessions), {self.player.player_id})

    async def test_wrong_pin_sends_no_application_bytes_or_credentials(self):
        received = asyncio.get_running_loop().create_future()
        async def capture(reader, writer):
            self.writers.append(writer)
            received.set_result(await reader.read(16_388))
        listener = await asyncio.start_server(capture, "127.0.0.1", 0, ssl=self.server_tls.build_context(),
                                              ssl_handshake_timeout=1, ssl_shutdown_timeout=0.3)
        self.listeners.append(listener)
        address = listener.sockets[0].getsockname()[:2]
        c = self.companion(address)
        c.config = replace(c.config, server_tls=replace(self.client_tls, certificate_sha256="0" * 64))
        with self.assertRaises(HostIdentityError):
            await c._remote_once()
        self.assertEqual(await asyncio.wait_for(received, 2), b"")
        self.assertIsNone(c._remote_writer)
        self.assertFalse(c.connected)

    async def test_untrusted_certificate_fails_even_when_exact_leaf_pin_matches(self):
        self.expected_tls_rejection = True
        await self.server.start("127.0.0.1", 0, tls=self.server_tls)
        other_cert = self.identities[1][0]
        c = self.companion(self.server.address)
        c.config = replace(c.config, server_tls=ClientTlsConfig(other_cert, self.identities[0][2]))
        c._server_tls_context = c.config.server_tls.build_context()
        with self.assertRaises(ssl.SSLCertVerificationError):
            await c._remote_once()
        self.assertFalse(c.connected)
        self.assertFalse(self.server.sessions)
        self.assertIsNone(c._remote_writer)

    async def test_expired_trusted_pinned_certificate_still_fails_validation(self):
        self.expected_tls_rejection = True
        cert, key, pin = self.identities[2]
        await self.server.start("127.0.0.1", 0, tls=ServerTlsConfig(cert, key))
        c = self.companion(self.server.address)
        c.config = replace(c.config, server_tls=ClientTlsConfig(cert, pin))
        c._server_tls_context = c.config.server_tls.build_context()
        with self.assertRaises(ssl.SSLCertVerificationError):
            await c._remote_once()
        self.assertFalse(c.connected)
        self.assertFalse(self.server.sessions)

    async def test_client_tls_handshake_timeout_sends_no_credential_and_does_not_hang(self):
        received = asyncio.get_running_loop().create_future()
        finished = asyncio.Event()
        async def stalled(reader, writer):
            self.writers.append(writer)
            received.set_result(await reader.read(16_388))
            await finished.wait()
        listener = await asyncio.start_server(stalled, "127.0.0.1", 0)
        self.listeners.append(listener)
        c = self.companion(listener.sockets[0].getsockname()[:2])
        c.config = replace(c.config, server_tls=replace(self.client_tls, handshake_timeout=0.15))
        try:
            async with asyncio.timeout(2):
                with self.assertRaises((asyncio.TimeoutError, ConnectionError)):
                    await c._remote_once()
            self.assertFalse(c.connected)
            self.assertIsNone(c._remote_writer)
            data = await asyncio.wait_for(received, 1)
            self.assertNotIn(c.config.server_credential.hex().encode(), data)
            self.assertNotIn(b'"hello"', data)
        finally:
            finished.set()

    async def test_plaintext_client_and_stalled_handshake_cannot_reach_hello(self):
        self.expected_tls_rejection = True
        await self.server.start("127.0.0.1", 0, tls=self.server_tls, public=True)
        for payload in (encode_message({"type": "hello", "protocol": 1}), b""):
            reader, writer = await asyncio.open_connection(*self.server.address)
            self.writers.append(writer)
            writer.write(payload)
            await writer.drain()
            try:
                response = await asyncio.wait_for(reader.read(128), 1.5)
                self.assertEqual(response, b"")
            except ConnectionError:
                pass
            self.assertFalse(self.server.sessions)
            self.assertFalse(self.server._handlers)
        self.assertEqual(self.store.metadata.session_epoch, 1)

    async def test_tls_does_not_replace_player_authentication(self):
        await self.server.start("127.0.0.1", 0, tls=self.server_tls, public=True)
        for credential in (None, secrets.token_bytes(32)):
            reader, writer = await asyncio.open_connection(*self.server.address, ssl=self.client_tls.build_context(),
                server_hostname=self.server.address[0], ssl_handshake_timeout=1, ssl_shutdown_timeout=0.3)
            self.writers.append(writer)
            self.client_tls.verify_peer(writer)
            hello = dict(type="hello", protocol=PROTOCOL_VERSION, build_id=self.base.build_id, ruleset_id=BASELINE_RULESET,
                         player_id=self.player.player_id, display_name="Player")
            if credential is not None:
                hello["credential"] = credential.hex()
            writer.write(encode_message(hello))
            await writer.drain()
            reply = await asyncio.wait_for(read_message(reader), 2)
            self.assertEqual(reply["type"], "error")
            self.assertFalse(self.server.sessions)
        self.assertEqual(self.store.metadata.session_epoch, 1)

    async def test_tls_known_host_is_distinct_from_expected_world(self):
        await self.server.start("127.0.0.1", 0, tls=self.server_tls)
        c = self.companion(self.server.address, expected_world_id=str(uuid4()))
        await c.start()
        await wait_until(lambda: c.last_error == "identity_mismatch")
        self.assertFalse(c.connected)
        self.assertIsNone(c.world_id)

    async def test_server_restart_keeps_certificate_world_and_checkpoint_fences_lease(self):
        await self.server.start("127.0.0.1", 0, tls=self.server_tls, public=True)
        address, world = self.server.address, self.store.metadata.world_id
        c = self.companion(address, public_server=True, expected_world_id=world)
        await c.start()
        await wait_until(lambda: c.connected)
        lease, epoch = c.session_epoch, c.server_epoch
        payload = make_flash()
        await CheckpointClient(c).upload(payload, expected_revision=0)
        await self.server.close()
        await wait_until(lambda: not c.connected)
        self.store.close()
        self.store = CheckpointStore(Path(self.temp.name) / "world.sqlite3", self.base.build_id, BASELINE_RULESET, LAYOUT_ID)
        self.server = WorldServer(self.config, store=self.store)
        await self.server.start(*address, tls=self.server_tls, public=True)
        await wait_until(lambda: c.connected and c.server_epoch > epoch)
        self.assertGreater(c.session_epoch, lease)
        self.assertEqual(c.world_id, world)
        self.assertEqual((await CheckpointClient(c).download()).payload, payload)

    async def test_public_server_config_rejects_plain_ephemeral_wildcard_before_bind_or_boot(self):
        for host, changes in (("127.0.0.1", {}), ("0.0.0.0", {"tls": self.server_tls}),
                              ("::", {"tls": self.server_tls}), ("example.com", {"tls": self.server_tls}),
                              ("224.0.0.1", {"tls": self.server_tls})):
            with self.subTest(host=host), self.assertRaises(ValueError):
                await self.server.start(host, 0, public=True, **changes)
        ephemeral = WorldServer(self.config)
        with self.assertRaises(ValueError):
            await ephemeral.start("127.0.0.1", 0, tls=self.server_tls, public=True)
        self.assertEqual(self.store.metadata.server_epoch, 0)
        self.assertIsNone(self.server._server)

    async def test_tls_client_never_downgrades_to_plaintext(self):
        received = asyncio.get_running_loop().create_future()
        async def plain(reader, writer):
            self.writers.append(writer)
            data = await reader.read(16_388)
            received.set_result(data)
            writer.write(encode_message({"type": "error", "protocol": 1, "code": "plain", "message": "plain"}))
            await writer.drain()
            writer.close()
        listener = await asyncio.start_server(plain, "127.0.0.1", 0)
        self.listeners.append(listener)
        c = self.companion(listener.sockets[0].getsockname()[:2])
        with self.assertRaises((ssl.SSLError, ConnectionError)):
            await c._remote_once()
        data = await asyncio.wait_for(received, 2)
        self.assertNotIn(c.config.server_credential.hex().encode(), data)
        self.assertNotIn(b'"hello"', data)
        self.assertFalse(c.connected)


if __name__ == "__main__":
    unittest.main()
