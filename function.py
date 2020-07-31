import os
import random
import numpy as np
from time import gmtime, strftime
from tensorflow.keras.layers import Input, Dense, Activation, BatchNormalization
from tensorflow.keras.models import Model
from tensorflow.keras.losses import mean_squared_error, categorical_crossentropy
from tensorflow.keras.datasets import mnist
from tensorflow.keras.utils import to_categorical
from tensorflow.keras.callbacks import TensorBoard, Callback


# 浸透サブネットおよび全体のネットワークの構成
def network(input_shape, num_percfeature, num_classes,
            num_layers_percnet, num_layers_intnet,
            num_elements_percnet, num_elements_intnet):
    input_img = Input(shape=input_shape)
    x = input_img
    for i in range(num_layers_percnet):
        if i == num_layers_percnet - 1:
            x = Dense(num_percfeature)(x)
        else:
            x = Dense(num_elements_percnet)(x)
        x = BatchNormalization()(x)
        x = Activation('relu')(x)
    feature = x
    percnet = Model(input_img, feature)

    x = percnet.output
    for i in range(num_layers_intnet - 1):
        x = Dense(num_elements_intnet)(x)
        x = BatchNormalization()(x)
        x = Activation('relu')(x)
    x = Dense(num_classes)(x)
    output = Activation('softmax')(x)
    network = Model(percnet.input, output)

    return percnet, network


# MNISTデータセットの準備
class MNISTDataset():
    def __init__(self):
        self.num_input = 784
        self.num_classes = 10

    # MNISTデータセットの取得
    def get_data(self):
        (x_train, y_train), (x_test, y_test) = mnist.load_data()
        # 出力データをone-hotベクトルによる表現にする
        y_train = to_categorical(y_train, self.num_classes)
        y_test = to_categorical(y_test, self.num_classes)
        # 各データが0~1の値となるように調整
        x_train = x_train.astype('float32') / 255
        x_test = x_test.astype('float32') / 255
        # 28*28ピクセルのデータを784個のデータに平滑化
        x_train = x_train.reshape([len(x_train), self.num_input])
        x_test = x_test.reshape([len(x_test), self.num_input])
        return x_train, y_train, x_test, y_test


# 主データと補助データの準備
def get_main_aux_data(x, y, validation_split, test_split, shuffle_rate):
    x_main = shuffle_pixel(x, shuffle_rate)
    x = np.concatenate([x, x_main], axis=1)
    id_test = int(test_split * x.shape[0])
    id_val = int(validation_split * x.shape[0])
    x_train = x[:-(id_val + id_test)]
    y_train = y[:-(id_val + id_test)]
    x_val = x[-(id_val + id_test):-id_test]
    y_val = y[-(id_val + id_test):-id_test]
    x_test = x[-id_test:]
    y_test = y[-id_test:]
    return x_train, y_train, x_val, y_val, x_test, y_test


# 学習させるためのクラス
class Trainer():

    def __init__(self, model_percnet, model_wholenet, optimizer, verbose):
        self.model_percnet = model_percnet
        self.model_wholenet = model_wholenet
        self.model_percnet.compile(loss=mean_squared_error, optimizer=optimizer)
        self.model_wholenet.compile(loss=categorical_crossentropy, optimizer=optimizer, metrics=['accuracy'])
        self.verbose = verbose

    # 学習
    def train(self, x_train, y_train,
              x_val, y_val,
              auxdt_size,
              batch_size,
              epochs_prior, epochs_perc, epochs_adj,
              decay,
              history):
        # 1：事前学習
        self.model_wholenet.summary()
        self.model_wholenet.fit(x_train, y_train,
                                epochs=epochs_prior,
                                batch_size=batch_size,
                                verbose=self.verbose,
                                validation_data=(x_val, y_val),
                                callbacks=[history])

        # 浸透特徴の保存
        perc_feature = self.model_percnet.predict(x_train)
        perc_feature_val = self.model_percnet.predict(x_val)

        # 2：浸透学習
        epoch = 0
        loss = 1
        non_perc_rate = 1  # 非浸透率の初期値
        nprate_min = 1e-8  # 非浸透率の閾値
        loss_min = 1e-5  # 損失関数の値の閾値
        # 補助データに非浸透率を掛けるための配列を作成
        non_perc_vec = np.ones(x_train.shape[1])
        non_perc_vec[:auxdt_size] = 1 - decay

        '''
        # 統合サブネットの重みを固定
        for i in range(3 * (layers_intnet - 1) + 2):
            network.layers[-i-1].trainable = False
        network.compile(optimizer=optimizer, loss=categorical_crossentropy, metrics=['accuracy'])
        '''

        # 浸透学習
        self.model_percnet.summary()
        while non_perc_rate > nprate_min or loss > loss_min:
            non_perc_rate = (1 - decay) ** epoch
            print('Non-Percolation Rate =', non_perc_rate)
            self.model_percnet.fit(x_train, perc_feature,
                                   initial_epoch=epochs_prior + epoch, epochs=epochs_prior + epoch + 1,
                                   batch_size=batch_size,
                                   verbose=self.verbose,
                                   validation_data=(x_val, perc_feature_val))
            ev = self.model_wholenet.evaluate(x_train, y_train, batch_size=batch_size, verbose=0)
            ev_val = self.model_wholenet.evaluate(x_val, y_val, batch_size=batch_size, verbose=0)
            history.losses.append(ev[0])
            history.accuracy.append(ev[1])
            history.losses_val.append(ev_val[0])
            history.accuracy_val.append(ev_val[1])
            loss = self.model_percnet.evaluate(x_train, perc_feature, verbose=0)
            x_train *= non_perc_vec
            epoch += 1
            if epoch >= epochs_perc:
                break

        # 3：微調整
        '''
        # 統合サブネットの重み固定を解除
        for i in range(3 * (layers_intnet - 1) + 2):
            network.layers[-i-1].trainable = True
        network.compile(optimizer=optimizer, loss=categorical_crossentropy, metrics=['accuracy'])
        network.summary()
        '''
        if True:  # 微調整を行う条件を入れる(現状は常に微調整を行う)
            non_perc_vec[:auxdt_size] = 0
            x_train *= non_perc_vec
            self.model_wholenet.fit(x_train, y_train,
                                    initial_epoch=epochs_prior + epochs_perc,
                                    epochs=epochs_prior + epoch + epochs_adj,
                                    batch_size=batch_size,
                                    verbose=self.verbose,
                                    validation_data=(x_val, y_val),
                                    callbacks=[history])

        return history


# Tensorboardの作成
def make_tensorboard(set_dir_name=''):
    tictoc = strftime('%a_%d_%b_%Y_%H_%M_%S', gmtime())
    directory_name = tictoc
    log_dir = set_dir_name + '_' + directory_name
    os.mkdir(log_dir)
    tensorboard = TensorBoard(log_dir=log_dir)
    return tensorboard


# lossおよびAccuracyを保存するためのクラス
class LossAccHistory(Callback):
    def __init__(self):
        self.losses = []
        self.accuracy = []
        self.losses_val = []
        self.accuracy_val = []

    def on_epoch_end(self, epoch, logs={}):
        self.losses.append(logs.get('loss'))
        self.accuracy.append(logs.get('accuracy'))
        self.losses_val.append(logs.get('val_loss'))
        self.accuracy_val.append(logs.get('val_accuracy'))


# 画像のピクセルのうちshuffle_rate(0~1)の割合のものをシャッフルする関数
def shuffle_pixel(data, shuffle_rate):
    dtsize = data.shape[1]
    dtnum_shuffled = int(dtsize * shuffle_rate)
    id_shuffled = []
    i = 0
    while i < dtnum_shuffled:
        rnd = random.randint(0, dtsize - 1)
        if not rnd in id_shuffled:
            id_shuffled.append(rnd)
            i += 1
    id_shuffled = np.array(id_shuffled)
    id = id_shuffled
    id_shuffled = np.random.permutation(id_shuffled)
    idlist = np.arange(dtsize)
    for j in range(dtnum_shuffled):
        idlist[id[j]] = idlist[id_shuffled[j]]
    data = data[:, idlist]
    return data


def shuffle_datasets(x, y):
    dtsize = len(x)
    id_shuffled = np.arange(dtsize)
    id_shuffled = np.random.permutation(id_shuffled)
    x_out = x[id_shuffled, :]
    y_out = y[id_shuffled, :]
    return x_out, y_out

