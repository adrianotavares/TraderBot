export CERT_PATH=/Users/Shared/aws_crt/Zscaler_root.crt
export CERT_DIR=/Users/Shared/aws_crt/
export SSL_CERT_FILE=${CERT_PATH}
export SSL_CERT_DIR=${CERT_DIR}
export REQUESTS_CA_BUNDLE=${CERT_PATH}

clear

python3 src/main.py