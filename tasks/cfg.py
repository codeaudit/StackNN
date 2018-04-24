from __future__ import division

import random

import nltk.grammar as cfg
import torch
import torch.nn as nn
from nltk.parse.generate import generate
from torch.autograd import Variable

from base import Task


class CFGTask(Task):
    """
    In this task, the neural network will read a sentence (sequence of
    words) and predict the next word. We may specify a list of words
    that must be predicted by the grammar. For example, if we specify
    that the grammar must predict verbs, then we only evaluate the
    neural network based on the predictions made when the correct answer
    is a verb. The input and output data used for training and
    evaluation are based on examples uniformly sampled from a set of
    sentences generated by a deterministic context-free grammar.
    """

    def __init__(self,
                 grammar,
                 to_predict,
                 sample_depth,
                 model_type,
                 batch_size=10,
                 criterion=nn.CrossEntropyLoss(),
                 cuda=False,
                 epochs=30,
                 learning_rate=0.01,
                 l2_weight=0.01,
                 max_length=25,
                 null=u"#",
                 read_size=2,
                 verbose=True):
        """
        Constructor for the CFGTask object. To create a CFGTask, the
        user must specify a grammar to sample sentences from, a list of
        words that will be predicted as part of the task, the depth to
        which sentences from the grammar will be sampled to create
        training and testing data sets, and the type of neural network
        model that will be trained and evaluated.

        :type grammar: cfg.CFG
        :param grammar: A context-free grammar from which sentences will
            be drawn

        :type to_predict: list
        :param to_predict: The words that will be predicted in this task

        :type sample_depth: int
        :param sample_depth: The maximum depth to which sentences will
            be sampled from the grammar

        :type model_type: type
        :param model_type: The model that will be trained and evaluated.
            For this task, please pass the *type* of the model to the
            constructor, not an instance of the model class

        :type batch_size: int
        :param batch_size: The number of trials in each batch

        :type criterion: nn.modules.loss._Loss
        :param criterion: The error function used for training the model

        :type cuda: bool
        :param cuda: If True, CUDA functionality will be used

        :type epochs: int
        :param epochs: The number of training epochs that will be
            performed when executing an experiment

        :type learning_rate: float
        :param learning_rate: The learning rate used for training

        :type l2_weight: float
        :param l2_weight: The amount of l2 regularization used for
            training

        :type max_length: int
        :param max_length: The maximum length of a string that will
            appear in the input training and testing data

        :type read_size: int
        :param read_size: The length of the vectors stored on the neural
            data structure

        :type verbose: bool
        :param verbose: If True, the progress of the experiment will be
            displayed in the console
        """
        self.grammar = grammar
        self.code_for = self._get_code_for(null)
        self.num_words = len(self.code_for)

        super(CFGTask, self).__init__(batch_size=batch_size,
                                      criterion=criterion,
                                      cuda=cuda,
                                      epochs=epochs,
                                      learning_rate=learning_rate,
                                      l2_weight=l2_weight,
                                      max_x_length=max_length,
                                      max_y_length=max_length,
                                      model_type=model_type,
                                      read_size=read_size,
                                      verbose=verbose)

        self.to_predict_code = self.words_to_code(*to_predict)
        self.sample_depth = sample_depth
        self.null = null
        self.max_length = max_length

        self.sample_strings = self.generate_sample_strings()

        return

    def reset_model(self, model_type):
        """
        Instantiates a neural network model of a given type that is
        compatible with this Task. This function must set self.model to
        an instance of model_type

        :type model_type: type
        :param model_type: A type from the models package. Please pass
            the desired model's *type* to this parameter, not an
            instance thereof

        :return: None
        """
        self.model = model_type(self.num_words, self.read_size, self.num_words)

    def _get_code_for(self, null):
        """
        Creates an encoding of a CFG's terminal symbols as numbers.

        :type grammar: cfg.CFG
        :param grammar: A CFG

        :type null: unicode
        :param null: A string representing "null"

        :rtype: dict
        :return: A dict associating each terminal of the grammar with a
            unique number. The highest number represents "null"
        """
        rhss = [r.rhs() for r in self.grammar.productions()]
        rhs_symbols = set()
        rhs_symbols.update(*rhss)
        rhs_symbols = set(x for x in rhs_symbols if cfg.is_terminal(x))

        code_for = {x: i for i, x in enumerate(rhs_symbols)}
        code_for[null] = len(code_for)

        return code_for

    """ Model Training """

    def _evaluate_step(self, x, y, a, j):
        """
        Computes the loss, number of guesses correct, and total number
        of guesses when reading the jth symbol of the input string. If
        the correct answer for a prediction does not appear in
        self.to_predict, then we consider the loss for that prediction
        to be 0.

        :type x: Variable
        :param x: The input data, represented as a 3D tensor. For each
            i and j, x[i, j, :] is the jth symbol of the ith sentence of
            the batch, represented as a one-hot vector

        :type y: Variable
        :param y: The output data, represented as a 2D tensor. For each
            i and j, y[i, j] is the (j + 1)st symbol of the ith sentence
            of the batch, represented numerically according to
            self.code_for. If the length of the sentence is less than
            j, then y[i, j] is "null"

        :type a: Variable
        :param a: The output of the neural network after reading the jth
            word of the sentence, represented as a 2D vector. For each
            i, a[i, :] is the network's prediction for the (j + 1)st
            word of the sentence, in one-hot representation

        :type j: int
        :param j: The jth word of a sentence is being read by the neural
            network when this function is called

        :rtype: tuple
        :return: The loss, number of correct guesses, and number of
            total guesses after reading the jth word of the sentence
        """
        _, y_pred = torch.max(a, 1)

        # Find the batch trials where we make a prediction
        null = self.code_for[self.null]
        valid_x = (y[:, j] != null).type(torch.FloatTensor)
        for k in xrange(len(valid_x)):
            if y[k, j].data[0] not in self.to_predict_code:
                valid_x[k] = 0

        correct_trials = (y_pred == y[:, j]).type(torch.FloatTensor)
        correct = sum((valid_x * correct_trials).data)
        total = sum(valid_x.data)
        loss = torch.mean(valid_x * self.criterion(a, y[:, j]))

        return loss, correct, total

    """ Data Generation """

    def get_data(self):
        """
        Generates training and testing datasets for this task using the
        self.get_tensors method.

        :return: None
        """
        self.train_x, self.train_y = self.get_tensors(800)
        self.test_x, self.test_y = self.get_tensors(100)

        return

    def generate_sample_strings(self, remove_duplicates=True):
        """
        Generates all strings from self.grammar up to the depth
        specified by self.depth. Duplicates may optionally be removed.

        :type remove_duplicates: bool
        :param remove_duplicates: If True, duplicates will be removed

        :rtype: list
        :return: A list of strings generated by self.grammar
        """
        generator = generate(self.grammar, depth=self.sample_depth)
        if remove_duplicates:
            return [list(y) for y in set(tuple(x) for x in generator)]
        else:
            return list(generator)

    def get_tensors(self, num_tensors):
        """
        Generates a dataset for this task. Each input consists of a
        sentence generated by self.grammar. Each output consists of a
        list of words such that the jth word is the correct prediction
        the neural network should make after having read the jth input
        word. In this case, the correct prediction is the next word.

        Input words are represented in one-hot encoding. Output words
        are represented numerically according to self.code_for. Each
        sentence is truncated to a fixed length of self.max_length. If
        the sentence is shorter than this length, then it is padded with
        "null" symbols. The dataset is represented as two tensors, x and
        y; see self._evaluate_step for the structures of these tensors.

        :type num_tensors: int
        :param num_tensors: The number of sentences to include in the
            dataset

        :rtype: tuple
        :return: A Variable containing the input dataset and a Variable
            containing the output dataset
        """
        x_raw = [self.get_random_sample_string() for _ in xrange(num_tensors)]
        y_raw = [s[1:] for s in x_raw]

        # Initialize x to all nulls
        x = torch.FloatTensor(num_tensors, self.max_length, len(self.code_for))
        x[:, :, :-1].fill_(0)
        x[:, :, -1].fill_(1)

        # Fill in x values
        for i, words in enumerate(x_raw):
            words_one_hot = self.words_to_one_hot(*words)
            for j, word in enumerate(words_one_hot[:self.max_length]):
                x[i, j, :] = word

        # Initialize y to all nulls
        y = torch.LongTensor(num_tensors, self.max_length)
        y[:, :].fill_(self.code_for[self.null])

        # Fill in y values
        for i, words in enumerate(y_raw):
            words_code = self.words_to_code(*words)
            for j, word in enumerate(words_code[:self.max_length]):
                y[i, j] = word

        return Variable(x), Variable(y)

    def get_random_sample_string(self):
        """
        Randomly chooses a sentence from self.sample_strings with a
        uniform distribution.

        :rtype: list
        :return: A sentence from self.sample_strings
        """
        return random.choice(self.sample_strings)

    def words_to_code(self, *words):
        """
        Converts one or more words to numerical representation according
        to self.code_for.

        :type words: unicode
        :param words: One or more words

        :rtype: list
        :return: A list containing the numerical encodings of words
        """
        return [self.code_for[word] for word in words]

    def words_to_one_hot(self, *words):
        """
        Converts one or more words to one-hot representation.

        :type words: unicode
        :param words: One or more words

        :rtype: list
        :return: A list containing the one-hot encodings of words
        """
        size = len(self.code_for)
        codes = [self.code_for[x] for x in words]

        return [CFGTask.one_hot(x, size) for x in codes]

    @staticmethod
    def one_hot(number, size):
        """
        Computes the following one-hot encoding:
            0 -> [1., 0., 0., ..., 0.]
            1 -> [0., 1., 0., ..., 0.]
            2 -> [0., 0., 1., ..., 0.]
        etc.

        :type number: int
        :param number: A number

        :type size: int
        :param size: The number of dimensions of the one-hot vector.
            There should be at least one dimension corresponding to each
            possible value for number

        :rtype: torch.FloatTensor
        :return: The one-hot encoding of number
        """
        return torch.FloatTensor([float(i == number) for i in xrange(size)])
