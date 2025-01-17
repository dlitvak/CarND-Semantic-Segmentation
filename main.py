#!/usr/bin/env python3
import os.path
import tensorflow as tf
import helper
import warnings
from distutils.version import LooseVersion
import project_tests as tests

NUM_EPOCHS = 50
BATCH_SIZE = 16
KP_VALUE = 0.5  # Keep prob = 1 - Droput rate
LR_VALUE = 0.001  # learning rate

# Check TensorFlow Version
assert LooseVersion(tf.__version__) >= LooseVersion('1.0'), 'Please use TensorFlow version 1.0 or newer.  You are using {}'.format(tf.__version__)
print('TensorFlow Version: {}'.format(tf.__version__))

# Check for a GPU
if not tf.test.gpu_device_name():
    warnings.warn('No GPU found. Please use a GPU to train your neural network.')
else:
    print('Default GPU Device: {}'.format(tf.test.gpu_device_name()))


def load_vgg(sess, vgg_path):
    """
    Load Pretrained VGG Model into TensorFlow.
    :param sess: TensorFlow Session
    :param vgg_path: Path to vgg folder, containing "variables/" and "saved_model.pb"
    :return: Tuple of Tensors from VGG model (image_input, keep_prob, layer3_out, layer4_out, layer7_out)
    """

    #   Use tf.saved_model.loader.load to load the model and weights
    vgg_tag = 'vgg16'
    vgg_input_tensor_name = 'image_input:0'
    vgg_keep_prob_tensor_name = 'keep_prob:0'
    vgg_layer3_out_tensor_name = 'layer3_out:0'
    vgg_layer4_out_tensor_name = 'layer4_out:0'
    vgg_layer7_out_tensor_name = 'layer7_out:0'

    tf.saved_model.loader.load(sess, [vgg_tag], vgg_path)
    graph = tf.get_default_graph()
    input = graph.get_tensor_by_name(vgg_input_tensor_name)
    keep = graph.get_tensor_by_name(vgg_keep_prob_tensor_name)
    layer3 = graph.get_tensor_by_name(vgg_layer3_out_tensor_name)
    layer4 = graph.get_tensor_by_name(vgg_layer4_out_tensor_name)
    layer7 = graph.get_tensor_by_name(vgg_layer7_out_tensor_name)

    return input, keep, layer3, layer4, layer7
tests.test_load_vgg(load_vgg, tf)


def layers(vgg_layer3_out, vgg_layer4_out, vgg_layer7_out, num_classes):
    """
    Create the layers for a fully convolutional network.  Build skip-layers using the vgg layers.
    :param vgg_layer3_out: TF Tensor for VGG Layer 3 output
    :param vgg_layer4_out: TF Tensor for VGG Layer 4 output
    :param vgg_layer7_out: TF Tensor for VGG Layer 7 output
    :param num_classes: Number of classes to classify
    :return: The Tensor for the last layer of output
    """

    # Skip dense layers. Apply 1x1 convolution to reduce the number of filters from 4096 to num_classes (2)
    fcn_layer8 = tf.layers.conv2d(vgg_layer7_out, filters=num_classes, kernel_size=1, name="fcn_layer8")

    # Upsample fcn_layer8 to match the size of pooling layer 4 in order to be able to add skip connection (from 4th to 8th layer)
    fcn_layer9 = tf.layers.conv2d_transpose(fcn_layer8, filters=vgg_layer4_out.get_shape().as_list()[-1], kernel_size=4, strides=(2, 2), padding='SAME', name="fcn_layer9")

    # Add a skip connection between vgg16 4th layer and fcn_layer8/fcn_layer9
    fcn_layer9_skip_from_layer4 = tf.add(fcn_layer9, vgg_layer4_out, name="fcn_layer9_skip_from_vgg_layer4")

    # Upsample once more to skip from vgg layer 3
    fcn_layer10 = tf.layers.conv2d_transpose(fcn_layer9_skip_from_layer4, filters=vgg_layer3_out.get_shape().as_list()[-1], kernel_size=4, strides=(2, 2), padding='SAME', name="fcn10_conv2d")

    # Skip connection from pool layer 3
    fcn_layer10_skip_from_layer3 = tf.add(fcn_layer10, vgg_layer3_out, name="fcn10_skip_from_vgg_layer3")

    # Upsample once more to reach the image size
    fcn_layer11 = tf.layers.conv2d_transpose(fcn_layer10_skip_from_layer3, filters=num_classes, kernel_size=16, strides=(8, 8), padding='SAME', name="fcn_layer11")

    return fcn_layer11
tests.test_layers(layers)


def optimize(nn_last_layer, correct_label, learning_rate, num_classes):
    """
    Build the TensorFLow loss and optimizer operations.
    :param nn_last_layer: TF Tensor of the last layer in the neural network
    :param correct_label: TF Placeholder for the correct label image
    :param learning_rate: TF Placeholder for the learning rate
    :param num_classes: Number of classes to classify
    :return: Tuple of (logits, train_op, cross_entropy_loss)
    """

    # Reshape 4D tensors to 2D: row is an image pixel, column is a class: road or not-road
    logits = tf.reshape(nn_last_layer, (-1, num_classes), name="fcn_logits")
    training_y_labels = tf.reshape(correct_label, (-1, num_classes))

    # Calculate distance between fcn logits and the training labels
    cross_entropy = tf.nn.softmax_cross_entropy_with_logits(logits=logits, labels=training_y_labels[:])
    # Obtain mean of the logit distance: softmax_cross_entropy
    cross_entropy_loss = tf.reduce_mean(cross_entropy, name="fcn_loss")

    # Adam optimizer: gradient descent
    train_op = tf.train.AdamOptimizer(learning_rate=learning_rate).minimize(cross_entropy_loss, name="fcn_train_op")

    return logits, train_op, cross_entropy_loss
tests.test_optimize(optimize)


def train_nn(sess, epochs, batch_size, get_batches_fn, train_op, cross_entropy_loss, input_image,
             correct_label, keep_prob, learning_rate):
    """
    Train neural network and print out the loss during training.
    :param sess: TF Session
    :param epochs: Number of epochs
    :param batch_size: Batch size
    :param get_batches_fn: Function to get batches of training data.  Call using get_batches_fn(batch_size)
    :param train_op: TF Operation to train the neural network
    :param cross_entropy_loss: TF Tensor for the amount of loss
    :param input_image: TF Placeholder for input images
    :param correct_label: TF Placeholder for label images
    :param keep_prob: TF Placeholder for dropout keep probability
    :param learning_rate: TF Placeholder for learning rate
    """
    for epoch in range(epochs):
        # Create function to get batches
        total_loss = 0
        for X_batch, y_batch in get_batches_fn(batch_size):
            loss, _ = sess.run([cross_entropy_loss, train_op],
                               feed_dict={input_image: X_batch, correct_label: y_batch,
                                          keep_prob: KP_VALUE, learning_rate: LR_VALUE})

            total_loss += loss

        print("EPOCH {} ...".format(epoch + 1))
        print("Loss = {:.3f}".format(total_loss))
        print()

tests.test_train_nn(train_nn)

def run():
    num_classes = 2
    image_shape = (160, 576)  # KITTI dataset uses 160x576 images
    data_dir = './data'
    runs_dir = './runs'

    correct_label = tf.placeholder(tf.float32, [None, image_shape[0], image_shape[1], num_classes])
    learning_rate = tf.placeholder(tf.float32)

    tests.test_for_kitti_dataset(data_dir)

    # Download pretrained vgg model
    helper.maybe_download_pretrained_vgg(data_dir)

    # OPTIONAL: Train and Inference on the cityscapes dataset instead of the Kitti dataset.
    # You'll need a GPU with at least 10 teraFLOPS to train on.
    #  https://www.cityscapes-dataset.com/

    with tf.Session() as sess:
        # Path to vgg model
        vgg_path = os.path.join(data_dir, 'vgg')
        # Create function to get batches
        get_batches_fn = helper.gen_batch_function(os.path.join(data_dir, 'data_road/training'), image_shape)

        # OPTIONAL: Augment Images for better results
        #  https://datascience.stackexchange.com/questions/5224/how-to-prepare-augment-images-for-neural-network

        # Build NN using load_vgg, layers, and optimize function
        img_input, keep_prob, layer3, layer4, layer7 = load_vgg(sess, vgg_path)
        model_out = layers(layer3, layer4, layer7, num_classes)
        logits, train_op, cross_entropy_loss = optimize(model_out, correct_label, learning_rate, num_classes)

        sess.run(tf.global_variables_initializer())

        # Train NN using the train_nn function
        train_nn(sess, NUM_EPOCHS, BATCH_SIZE, get_batches_fn,
                 train_op, cross_entropy_loss, img_input,
                 correct_label, keep_prob, learning_rate)

        # Save inference data using helper.save_inference_samples
        helper.save_inference_samples(runs_dir, data_dir, sess, image_shape, logits, keep_prob, img_input)

        # OPTIONAL: Apply the trained model to a video


if __name__ == '__main__':
    run()
